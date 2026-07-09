import re
from django.conf import settings

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken


from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests



from ..models import (
    User,
    EmailVerificationToken,
)

from .common import UserSummarySerializer

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends JWT payload with custom claims:
    user_id, role, is_verified, account_type.
    Also enforces account lockout check.
    """

    @classmethod
    def get_token(cls, user: User):
        token = super().get_token(user)
        # custom claims
        token["user_id"] = str(user.id)
        token["role"] = user.role or ""
        token["is_verified"] = user.is_verified
        token["account_type"] = user.account_type or ""
        return token

    def validate(self, attrs):
        # Attempt authentication
        email = attrs.get(self.username_field, "")
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid credentials.")

        # lockout check
        if user.is_locked_out:
            remaining = int((user.lockout_until - timezone.now()).total_seconds() / 60)
            raise serializers.ValidationError(
                f"Account is temporarily locked. Try again in {remaining} minute(s)."
            )

        try:
            data = super().validate(attrs)
        except Exception:
            user.record_failed_login()
            raise serializers.ValidationError("Invalid credentials.")

        # Successful login — clear lockout
        user.clear_failed_logins()

        # Attach user data to response
        data["user"] = UserSummarySerializer(self.user).data
        return data

class RegisterSerializer(serializers.ModelSerializer):
    """
    Register with email, username, phone_number, password.
    Optionally accepts google_token for Google OAuth flow.
    """
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True, required=True)
    google_token = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            'email',
            'username',
            'phone_number',
            'password',
            'confirm_password',
            'google_token'
        ]
        extra_kwargs = {
            "phone_number": {"required": False,},
        }
    def validate_email(self, value):
        if User.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()
    
    def validate_username(self, value):
        if not re.match(r"^[a-zA-Z0-9_]{3,50}$", value):
            raise serializers.ValidationError(
                "Username must be 3–50 alphanumeric characters or underscores."
            )
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value
    
    def validate_phone_number(self, value):
        if value and not re.match(r"^\+\d{7,15}$", value):
            raise serializers.ValidationError("Phone must be E.164 format, e.g. +237123456789")
        if value and User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("This phone number is already registered.")
        return value
    
    def validate(self, attrs):
        google_token = attrs.get('google_token')
        password = attrs.get('password')
        confirm = attrs.get('confirm_password')

        if not google_token and not password:
            raise serializers.ValidationError( {"password": "Password or google_token is required."})
        
        if password:
            try:
                validate_password(password)
            except DjangoValidationError as e:
                raise serializers.ValidationError(
                    {"password": e.messages}
                )

            if password != confirm:
                raise serializers.ValidationError(
                    {"confirm_password": "Passwords do not match."}
                )

        return attrs
        
    def create(self, validate_data):
        validate_data.pop('confirm_password', None)
        google_token = validate_data.pop('google_token', None)
        password = validate_data.pop('password', None)

        if google_token:
            google_info = self._verify_google_token(google_token)
            validate_data['google_uid'] = google_info['sub']
            validate_data['auth_provider'] = 'google'
            validate_data['is_email_verified'] = True

            user = User.objects.create_user(password=None, **validate_data)
        else:
            user = User.objects.create_user(password=password, **validate_data)
        
        return user
    
    @staticmethod
    def _verify_google_token(token: str) -> dict:
        """Validate Google ID token and return payload."""
        try:
            from google.oauth2 import id_token
            from google.auth.transport import requests as google_requests
            from django.conf import settings
            payload = id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_OAUTH2_CLIENT_ID,
            )
            return payload
        except Exception as exc:
            raise serializers.ValidationError(
                {"google_token": f"Invalid Google token: {exc}"}
            )

# Logout

class LogoutSerializer(serializers.Serializer):
    """Blacklist the refresh token on logout."""
    refresh = serializers.CharField()

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)
            self.context['token'] = token
        except Exception:
            raise serializers.ValidationError("Invalid refresh token.")
        return value
    def save(self):
        token : RefreshToken = self.context['token']
        token.blacklist()

class GoogleAuthSerializer(serializers.Serializer):
    """
    Google OAuth token exchange.
    Auto-creates account if first sign-in.
    """
    id_token = serializers.CharField()

    def validate_id_token(self, value):
        try:
            payload = google_id_token.verify_oauth2_token(
                value,
                google_requests.Request(),
                settings.GOOGLE_OAUTH2_CLIENT_ID,
            )
            return payload
        except Exception as exc:
            raise serializers.ValidationError(f"Invalid Google ID token: {exc}")
    
    def validate(self, attrs):
        payload = attrs['id_token']
        email = payload.get('email', '').lower()
        google_uid = payload.get('sub')
        name = payload.get('name', '')

        if not email:
            raise serializers.ValidationError("Google account has no associated email.")
        
        # Get or create user
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": self._derive_username(email),
                "google_uid": google_uid,
                "auth_provider": "google",
                "is_email_verified": True,
            },
        )

        if not created and not user.google_uid:
            # Link existing email account to Google
            user.google_uid = google_uid
            user.auth_provider = "google"
            user.save(update_fields=["google_uid", "auth_provider"])

        if not user.is_active:
            raise serializers.ValidationError("This account has been deactivated.")
        
        attrs["user"] = user
        attrs["created"] = created
        return attrs
    
    @staticmethod
    def _derive_username(email: str) -> str:
        base = email.split("@")[0].replace(".", "_").replace("-", "_")[:40]
        candidate = base
        counter = 1
        while User.objects.filter(username=candidate).exists():
            candidate = f"{base}_{counter}"
            counter += 1
        return candidate


