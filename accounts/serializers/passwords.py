from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

from ..models import (User, PasswordResetToken)

class PasswordResetRequestSerializer(serializers.Serializer):
    """
    Initiate password reset.
    Send a time-limited(1h), single-use token to verified email.
    """
    email = serializers.EmailField()

    def validate_email(self, value):
        try:
            user = User.objects.get(email=value.lower(), is_email_verified=True )
            self.context["user"] = user
        except User.DoesNotExist:
            pass # Silently ignore
        return value.lower()

class PasswordResetConfirmSerializer(serializers.Serializer):
    """
    Validate reset token 
    Returns user info if token is valid.
    """

    token = serializers.UUIDField()

    def validate_token(self, value):
        try:
            reset_token = PasswordResetToken.objects.select_related("user").get(token=value)
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError("Invalid or expired password reset link.")
        if not reset_token.is_valid:
            raise serializers.ValidationError(
                "This password reset link has expired or has already been used."
            )
        return reset_token

class SetNewPasswordSerializer(serializers.Serializer):
    """Consume reset token and set new password"""
    token = serializers.UUIDField()
    new_password = serializers.CharField(
        write_only=True, 
    )

    confirm_password = serializers.CharField(
        write_only=True
    )

    def validate_new_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return value

    def validate(Self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        try:
            reset_token = PasswordResetToken.objects.select_related("user").get(token=attrs["token"])
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError({"token":"Invalid reset token"})
        if not reset_token.is_valid:
            raise serializers.ValidationError({"token":"This reset link has expired or already been used."})
        attrs["reset_token"] = reset_token
        return attrs

    def save(self):
        reset_token: PasswordResetToken = self.validated_data["reset_token"]
        user = reset_token.user
        user.set_password(self.validated_data["new_password"])
        user.clear_failed_logins()
        user.save(update_fields=["password", "failed_login_attempts", "lockout_until"])

        #Invalidate token
        reset_token.is_used = True
        reset_token.save(update_fields=["is_used"])

        #Invalidate all active refresh tokens for security
        try:
            from rest_framework_simplejwt.token_blacklist.models import (
                OutstandingToken,
                BlacklistedToken,
            )

            for token in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=token)
        except Exception:
            pass
        return user

class ChangePasswordSerializer(serializers.Serializer):
    """Authenticated password change (requires current password)."""
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.message)
        return value

    def validate(self, attrs):
        user:User = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError(
                {"current_password":"Current password is incorrect."}
            )
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password":"Passwords do not match."}
            )
        return attrs

    def save(self):
        user:User = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
