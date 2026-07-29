import datetime
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class PasswordAwareJWTAuthentication(JWTAuthentication):
    """
    Rejects access tokens issued before the user's last password change.
    Adjacent — security hardening for credential rotation.
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        iat = validated_token.get("iat")
        if iat is not None and user.password_changed_at:
            issued_at = datetime.datetime.fromtimestamp(iat, tz=datetime.timezone.utc)
            if issued_at < user.password_changed_at:
                raise AuthenticationFailed(
                    "Token invalidated due to a recent password change.",
                    code="token_invalidated",
                )
        return user