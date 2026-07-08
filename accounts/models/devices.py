import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from .users import User


class DeviceToken(models.Model):
    """
    FCM device tokens for push notifications
    """

    class Platform(models.TextChoices):
        ANDROID = "android", _("Android")
        IOS     = "ios",     _("iOS")

    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user     = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="device_tokens"
    )
    token    = models.CharField(max_length=512, db_index=True)
    platform = models.CharField(max_length=10, choices=Platform.choices)
    is_active    = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(auto_now=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name    = _("device token")
        unique_together = [("user", "token")]

    def __str__(self):
        return f"Device [{self.platform}] — {self.user.email}"
