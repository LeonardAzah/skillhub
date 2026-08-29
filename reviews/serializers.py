from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers

from .models import Review, ProviderReviewSummary
from ._help import _validate_rating
from .services import check_review_eligibility
from .constants import TOP_RATED_MIN_AVERAGE, TOP_RATED_MIN_REVIEWS, PUBLIC_RATING_MIN

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


class EditReviewSerializer(serializers.Serializer):
    """Edits allowed within 24h of submission."""
    communication_rating = serializers.DecimalField(
        max_digits=2, decimal_places=1, required=False
    )
    punctuality_rating = serializers.DecimalField(
         max_digits=2, decimal_places=1, required=False
    )
    quality_rating = serializers.DecimalField(
        max_digits=2, decimal_places=1, required=False
    )
    comment = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )

    def validate_communication_rating(self, value):
        return _validate_rating(value)
    
    def validate_punctuality_rating(self, value):
        return _validate_rating(value)
    
    def validate_quality_rating(self, value):
        return _validate_rating(value)

    def validate(self, attrs):
        review: Review = self.context["review"]
        if not review.is_editable:
            raise serializers.ValidationError(
                "The 24-hour edit window for this review has closed."
            )

        if not attrs:
            raise serializers.ValidationError(
                "No fields provided to update."
            )
        return attrs

    def save(self) -> Review:
        review = self.context["review"]
        validated_value = self.validated_data
        update_fields = validated_value["updated_at"]
        for field in ("communication_rating", "punctuality_rating", "quality_rating", "comment"):
            if field in validated_value:
                setattr(review, field, validated_value[field])
                update_fields.append(field)
        review.save()

        return review

class ProviderReviewSummarySerializer(serializers.ModelSerializer):
    top_rated = serializers.SerializerMethodField()
    public_rating_visible = serializers.SerializerMethodField()

    class Meta:
        model = ProviderReviewSummary,
        fields = [
        "total_reviews",
        "avg_communication",
        "avg_punctuality",
        "avg_quality",
        "avg_overall",
        "star_distribution",
        "top_rated",
        "public_rating_visible",
        "last_updated",
        ]
        read_only_fields = fields

    def get_tio_rated(Self, obj) -> bool:
        return (
            obj.total_review >= TOP_RATED_MIN_REVIEWS and obj.avg_overall >= TOP_RATED_MIN_AVERAGE
        )

    def get_public_rating_visible(self, obj) -> bool:
        return obj.total_reviews >= PUBLIC_RATING_MIN

class ProviderResponseSerializer(serializers.Serializer):
    response_text = serializers.CharField(max_length=500)

    def validate(self, attrs):
        review: Review = self.context["review"]

        if review.provider_response:
            raise serializers.ValidationError(
                "You have alreday responded to this review"
            )
        return attrs
    def save(self) -> Review:
        review: Review =self.context["review"]
        review.provider_response = self.validated_data["response_text"]
        review.provider_response_at = timezone.now()
        review.save(update_fields=["provider_response", "provider_response_at", "updated_at"])
        return review

class FlagReviewSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)

class RemoveReviewSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)