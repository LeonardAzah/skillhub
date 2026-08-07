"""
Private utilities shared across view modules.
"""
from rest_framework.exceptions import ValidationError


def _frontend_url() -> str:
    from django.conf import settings
    return getattr(settings, "FRONTEND_URL", "http://localhost:3000")


def _setting(key: str, default):
    from django.conf import settings
    return getattr(settings, key, default)

def get_client_ip(request) -> str:
    """Extract the real client IP from the request, respecting proxies."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def get_idempotency_key(request) -> str:
    idempotency_key =request.headers.get("Idempotency-Key")

    if not idempotency_key:
                raise ValidationError(
                    {
                        "idempotency_key": [
                            "Idempotency-Key header is required."
                        ]
                    }
                )

    return idempotency_key


def invalidate_existing_tokens(self) -> None:
        """
        Call after a password change to invalidate all previously issued
        access and refresh tokens.
        """
        from django.utils import timezone as tz
        from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken

        self.password_changed_at = tz.now()
        self.save(update_fields=["password_changed_at"])

        outstanding = OutstandingToken.objects.filter(user=self)
        for token in outstanding:
            BlacklistedToken.objects.get_or_create(token=token)
