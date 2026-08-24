from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers

from .models import Review, ProviderReviewSummary
from ._help import _validate_rating
from .services import check_review_eligibility

from appointments.models import Appointment



class ReviewSerializer(serializers.ModelSerializer):
    """Full review detial - public read."""
    reviewer_name = serializers.CharField(source="reviewer.username", read_only=True)
    provider_id = serializers.UUIDField(source="provider.id", read_only=True)
    appointment_id = serializers.UUIDField(source="appointment.id", read_only=True)
    is_editable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Review
        fields =[
            "id",
            "appointment_id",
            "reviewer_name",
            "provider_id",
            "communication_rating",
            "punctuality_rating",
            "quality_rating",
            "overall_rating",
            "comment",
            "is_flagged",
            "is_visible",
            "provider_response",
            "provider_response_at",
            "is_editable",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

class ReviewListSerializer(serializers.ModelSerializer):
    """Provider profile review list."""
    reviewer_name = serializers.CharField(source="reviewer.username", read_only=True)

    class Meta:
        model  = Review
        fields = [
            "id",
            "reviewer_name",
            "communication_rating",
            "punctuality_rating",
            "quality_rating",
            "overall_rating",
            "comment",
            "provider_response",
            "provider_response_at",
            "created_at",
        ]
        read_only_fields = fields

class SubmitReviewSerializer(serializers.Serializer):
    """All three dimension ratings are required. """

    appointment_id = serializers.UUIDField()
    communication_rating = serializers.DecimalField(max_digits=2, decimal_places=1)
    punctuality_rating = serializers.DecimalField(max_digits=2, decimal_places=1)
    quality_rating = serializers.DecimalField(max_digits=2, decimal_places=1)
    comment = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_communication_rating(self, value):
        return _validate_rating(value)

    def validate_punctuality_rating(self, value):
        return _validate_rating(value)

    def validate_quality_rating(self, value):
        return _validate_rating(value)

    def validate(self, attrs):

        request = self.context["request"]
        seeker = request.user

        try:
            appointment = Appointment.objects.select_related(
                "customer", "provider"
            ).get(id=attrs["appointment_id"])
        except Appointment.DoesNotExist:
            raise serializers.ValidationError(
                {"appointment_id":"Appointment not found."}
            )

        try:
            check_review_eligibility(appointment=appointment, reviewer_seeker=seeker)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))

        attrs["_appointment"] = appointment
        attrs["_seeker"] = seeker
    
        return attrs

    def save(self) -> Review:
        validated_value = self.validated_data
        appointmtnet = validated_value["_appointment"]
        seeker = validated_value["_seeker"]

        review = Review.objects.create(
            appointmtnet = appointmtnet,
            reviewer = seeker,
            provider = appointmtnet.provider,
            communication_rating = validated_value["communication_rating"],
            punctuality_rating = validated_value["punctuality_rating"],
            quality_rating = validated_value["quality_rating"],
            comment = validated_value.get("comment", ""),
        )