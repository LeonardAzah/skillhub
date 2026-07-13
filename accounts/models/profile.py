
import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from .users import User

# Seeker Profile Model
class SeekerProfile(models.Model):
    """Service Seeker profile """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="seeker_profile"
    )
    full_name = models.CharField(_("full name"), max_length=256, blank=True)
    bio = models.TextField(_("bio"), max_length=1000, blank=True, default="")
    preferred_location_lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    preferred_location_lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("seeker profile")
        verbose_name_plural = _("seeker profiles")

    def __str__(self):
        return f"Seeker: {self.user.email}"
    

# Provider Profile Model
class ProviderProfile(models.Model):
    """
    Service Provider profile
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="provider_profile"
    )
    full_name = models.CharField(_("full name"), max_length=256, blank=True)
    bio = models.TextField(_("bio"), max_length=1000, blank=True, default="")
    hourly_rate      = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    service_radius_km = models.PositiveIntegerField(
        default=10,
        help_text=_("Max distance (km) provider is willing to travel."),
    )

    # Location (lat/lng for SQLite; use PostGIS Point in production)
    location_lat     = models.DecimalField(max_digits=24, decimal_places=16, null=True, blank=True)
    location_lng     = models.DecimalField(max_digits=24, decimal_places=16, null=True, blank=True)
    location_address = models.CharField(max_length=500, blank=True, default="")

    is_verified    = models.BooleanField(default=False)
    verified_badge = models.BooleanField(default=False)

    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    total_jobs     = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("provider profile")
        verbose_name_plural = _("provider profiles")
        indexes = [
            models.Index(fields=["is_verified"]),
            models.Index(fields=["average_rating"]),
        ]

    def __str__(self):
        return f"Provider: {self.user.email}"