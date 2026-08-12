"""
When a seeker initiates a booking they must have previously entered their
wallet PIN (POST /api/v1/payments/wallet/pin/verify — implemented in the payments
module).  That endpoint stores a short-lived cache token:

wallet_pin_verified:{seeker_id}   TTL = 5 minutes

The `CreateAppointmentSerializer` reads this token and raises a 400 if it
is absent or expired.  On successful booking the token is consumed (deleted)
so the PIN must be re-entered for the next booking.
"""

from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework import serializers
from rest_framework import status

from .models import Appointment, AppointmentStatusLog, ProviderAvailability
from ._helper import _wallet_pin_token_key

from accounts.models import ProviderProfile, User
from categories.models import Category, ProviderCategory
from utils.exceptions import error_response


class ProviderAvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model= ProviderAvailability
        fields = ["id", "blocked_date", "blocked_start", "blocked_end", "reason"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if attrs["blocked_start"] >= attrs["blocked_end"]:
            raise serializers.ValidationError("blocked_start must be before blocked_end.")
        return attrs

class AppointmentStatusLogSerializer(serializers.ModelSerializer):
    class Meta:
        model  = AppointmentStatusLog
        fields = ["from_status", "to_status", "actor_id", "reason", "timestamp"]
        read_only_fields = fields

class CreateAppointmentSerializer(serializers.Serializer):
    """
    Booking workflow.

    Wallet PIN gate
    ───────────────
    The seeker must have verified their wallet PIN via the payments module
    within the last 5 minutes.  That module stores the token:

        wallet_pin_verified:{seeker_id}   (Redis, TTL = 5 min)

    If the token is absent this serializer raises a 400 directing the seeker
    to verify their PIN first.  The token is consumed on successful booking.

    Other validations:
      - Provider exists and is KYC-verified
      - Provider offers the requested category
      - Date is today or in the future
      - Time slot is not already blocked or booked
      - quoted_price > 0
    """

    provider_id = serializers.UUIDField()
    category_slug = serializers.SlugField()
    location_address = serializers.CharField(max_length=500)
    location_lat = serializers.DecimalField(max_digits=24, decimal_places=16, required=False
    )
    location_lng = serializers.DecimalField(
        max_digits=24, decimal_places=16, required=False
    )
    scheduled_at = serializers.DateTimeField()
    notes = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )
    quoted_price = serializers.DecimalField(max_digits=10, decimal_places=2)

    def validate_scheduled_at(self, value):
        if value < datetime.now():
            raise serializers.ValidationError("Scheduled date/time must be today or the future.")

    def validate_quoted_price(self, value):
        if value <= 1000:
            raise serializers.ValidationError("Quoted price must be greater than 1000.")
        return value

    def validate(self, attrs):
        request = self.context["request"]
        seeker: User= request.user

        # wallet PIN must have been verified
        from django.core.cache import cache
        if not cache.get(_wallet_pin_token_key(seeker.id)):
            raise serializers.ValidationError("Please verify your wallet pin before booking")

        if seeker.id == provider.user_id:
            raise serializers.ValidationError(
                {"provider_id": "You cannot book an appointment with yourself."}
            )

        # validate provider
        try:
            provider = ProviderProfile.objects.select_related("user").get(
                id=attrs["provider_id"]
            )
        except ProviderProfile.DoesNotExist:
            raise serializers.ValidationError({
                "provider_id":"Provider not found"
            })

        if not provider.is_verified:
            raise serializers.ValidationError(
                {
                    "provider_id":"This provider has not verified"
                }
            )

        if not provider.user.is_active:
            raise serializers.ValidationError(
                {
                    "provider_id":"This provider account is not active."
                }
            )

        # category
        try:
            category = Category.objects.active().get(
                slug=attrs["category_slug"]
            )
        except Category.DoesNotExist:
            raise serializers.ValidationError(
                {
                    "category_slug":"Category not found or is inactive."
                    
                }
            )

        if not ProviderCategory.objects.filter(
            provider=provider, category=category
        ).exists(): raise serializers.ValidationError(
            {"category_slug": f"This provider does not offer '{category.title}'."}
        )

        # availability
        scheduled_at = attrs["scheduled_at"]
        if ProviderAvailability.objects.filter(
            provider=provider,
            blocked_date=scheduled_at.date(),
            blocked_start__lte=scheduled_at.time(),
            blocked_end__gt=scheduled_at.time(),
        ).exists(): raise serializers.ValidationError(
            "Provider is unavailable at the requested date and time."
        )

        if Appointment.objects.filter(
            provider=provider,
            scheduled_at=scheduled_at,
            status__in=[Appointment.Status.PENDING, Appointment.Status.ACCEPTED, Appointment.Status.IN_PROGRESS]
        ).exists():raise serializers.ValidationError(
            "Provider already has a booking at this time. Please chose another slot."
        )

        attrs["_provider"]=provider
        attrs["_category"]=category
        attrs["_seeker"]= seeker

        return attrs

    def save(self) -> Appointment:
        attrs = self.validated_data
        provider = attrs["_provider"]
        Category = attrs["_category"]
        seeker = attrs["_seeker"]

        appointment = Appointment.objects.create(
            provider=provider,
            customer=seeker,
            category=Category,
            location_address=attrs["location_address"],
            location_lat=attrs.get("location_lat"),
            location_lng=attrs.get("location_lng"),
            scheduled_at=attrs("scheduled_at"),
            notes=attrs.get("notes", ""),
            quoted_price=attrs["quoted_price"],
            status=Appointment.Status.PENDING,
        )

        AppointmentStatusLog.objects.create(
            appointment=appointment,
            from_status="",
            to_status=Appointment.Status.PENDING,
            actor_id=str(seeker.user.id)
        )

        # Consume the wallet pin token
        from django.core.cache import cache
        cache.delete(_wallet_pin_token_key(seeker.id))

        return appointment


class AppointmentListSerializer(serializers.ModelSerializer):
    """Lightweight list item."""
    provider_name  = serializers.CharField(source="provider.full_name", read_only=True)
    customer_name  = serializers.CharField(source="customer.full_name", read_only=True)
    category_title = serializers.CharField(source="category.title", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id", "provider_name", "customer_name",
            "category_title", "location_address",
            "scheduled_date", "scheduled_time",
            "quoted_price", "status",
            "created_at",
        ]
        read_only_fields = fields

class AppointmentListSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source="provider.user.display_name", read_only=True)
    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    category_title = serializers.CharField(source="category.title", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id", "status", "scheduled_at", "quoted_price", "final_price",
            "provider_name", "customer_name", "category_title",
            "location_address", "created_at",
        ]
        read_only_fields = fields
        

class AppointmentSerializer(serializers.ModelSerializer):
    provider_id=serializers.UUIDField(source="provider.id")
    provider_name = serializers.CharField(source="provider.user.display_name", read_only=True)
    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    customer_id=serializers.UUIDField(source="customer.id")
    category_title = serializers.CharField(source="category.title", read_only=True)
    category_slug = serializers.CharField(source="category.slug", read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)
    status_logs    = AppointmentStatusLogSerializer(many=True, read_only=True)


    class Meta:
        model = Appointment
        fields = [
            "id",
            "status",
            "is_terminal",
            "provider_id",
            "provider_name",
            "customer_name",
            "customer_id",
            "category_title",
            "category_slug",
            "location_address",
            "location_lat",
            "location_lng",
            "scheduled_at",
            "notes",
            "quoted_price",
            "final_price",
            "cancellation_reason",
            "completion_proof",
            "completion_notes",
            "reminder_sent_24h",
            "reminder_sent_2h",
            "accepted_at",
            "completed_at",
            "confirmed_at",
            "cancelled_at",
            "created_at",
            "updated_at",
            "status_logs"
        ]
        read_only_fields = fields

class AcceptAppointmentSerializer(serializers.Serializer):
    def validate(self, attrs):
        apt: Appointment = self.context["appointment"]
        if not apt.can_transition_to(Appointment.Status.ACCEPTED): raise serializers.ValidationError(
            f"Cannot accept an application with status {apt.status}"
        )

        return attrs

class RejectAppointmentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        apt:Appointment = self.context["appointment"]
        if not apt.can_transition_to(Appointment.Status.REJECTED):
            raise serializers.ValidationError(
                f"Cannot reject an appointment with status {apt.status}"
            )
        return attrs

class StartAppointmentSerializer(serializers.Serializer):
    def validate(self, attrs):
        apt:Appointment = self.context["appointment"]
        if not apt.can_transition_to(Appointment.Status.IN_PROGRESS):
            raise serializers.ValidationError(
                f"Cannot start an appointment with status '{apt.status}'."
            )
        return attrs

class CompleteAppointmentSerializer(serializers.Serializer):
    completion_prof = serializers.URLField(
        help_text="S3/cloudinary URL of the completion photo/video."
    )
    completion_notes = serializers.CharField(
        max_lenght=1000, required=False, allow_blank=True, default=""
    )
    final_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )

    def validate_final_price(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Final price must be greater than zero")
        return value

    def validate(self, attrs):
        apt: Appointment = self.context["appointment"]
        if not apt.can_transition_to(Appointment.Status.COMPLETED):
            raise serializers.ValidationError(
                f"Cannot complete an appointment with status '{apt.status}'."
            )
        return attrs

class ConfirmAppointmentSerializer(serializers.Serializer):
    def validate(self, attrs):
        apt:Appointment = self.context["appointment"]
        if not apt.can_transition_to(Appointment.Status.CONFIRMED):
            raise serializers.ValidationError(
                f"Cannot confirm an appointment with status '{apt.status}'."
            )
        return attrs

class CancleAppointmentSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        apt:Appointment = self.context["appointment"]
        if not apt.can_transition_to(Appointment.Status.CANCELLED):
            raise serializers.ValidationError(
                f"Cannot cancel an appointment with status '{apt.status}'."
            )
        return attrs


class DisputeAppointmentSerializer(serializers.Serializer):
    seeker_statement = serializers.CharField(max_length=2000)

    def validate(self, attrs):
        apt:Appointment = self.context["appointment"]

        if not Appointment.can_transition_to(Appointment.Status.DISPUTED):
            raise serializers.ValidationError(
                f"Cannot dispute an appointment with status '{apt.status}'."
            )

        if apt.completed_at:
            deadline = apt.completed_at + timedelta(hours=48)
            if timezone.now() > deadline:
                raise serializers.ValidationError(
                     "The 48-hour window to raise a dispute has passed."
                )
        return attrs