import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .users import User

class EmailVerificationToken(models.Model):
    """
    One-time email verification tokens. 24-hours expiry
    """
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user     = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="email_tokens"
    )
    token    = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    is_used  = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.expires_at:
            hours = getattr(settings, "EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS", 24)
            self.expires_at = timezone.now() + timedelta(hours=hours)
        super().save(*args, **kwargs)
    

    @property
    def is_valid(self) -> bool:
        """
        Check if the token is valid (not used and not expired).
        """
        return not self.is_used and timezone.now() < self.expires_at
    
    class Meta:
        verbose_name = _("Email Verification Token")
        ordering = ["-created_at"]
    
    def __str__(self):
        return f"EmailToken - {self.user.email} ({'valid' if self.is_valid else 'invalid'})"

# Password Reset Token 

class PasswordResetToken(models.Model):
    """
    Time-limited, single-use password reset tokens.
    1-hour expiry, single-use.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    token      = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    is_used    = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.expires_at:
            from django.conf import settings
            hours = getattr(settings, "PASSWORD_RESET_EXPIRY_HOURS", 1)
            self.expires_at = timezone.now() + timedelta(hours=hours)
        super().save(*args, **kwargs)

    @property
    def is_valid(self) -> bool:
        return not self.is_used and timezone.now() < self.expires_at

    class Meta:
        verbose_name = _("password reset token")
        ordering     = ["-created_at"]

    def __str__(self):
        return f"PasswordReset — {self.user.email} ({'valid' if self.is_valid else 'expired/used'})"


