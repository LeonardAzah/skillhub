"""
When a seeker initiates a booking they must have previously entered their
wallet PIN (POST /api/v1/payments/wallet/pin/verify — implemented in the payments
module).  That endpoint stores a short-lived cache token:

wallet_pin_verified:{seeker_id}   TTL = 5 minutes

The `CreateAppointmentSerializer` reads this token and raises a 400 if it
is absent or expired.  On successful booking the token is consumed (deleted)
so the PIN must be re-entered for the next booking.
"""

from datetime import date, timedelta

from django.utils import timezone
from rest_framework import serializers

from .models import Appointment, AppointmentStatusLog, ProviderAvailability

from accounts.models import ProviderProfile, SeekerProfile
from categories.models import Category, ProviderCategory


class ProviderAvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model= ProviderAvailability
        fields = ["id", "blocked_date", "blocked_start", "blocked_end", "reason"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if attrs["blocked_start"] >= attrs["blocked_end"]:
            raise serializers.ValidationError("blocked_start must be before blocked_end.")
        return attrs