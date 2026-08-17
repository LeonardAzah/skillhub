from django.utils import timezone
from rest_framework import serializers

from .models import Dispute, DisputeEvidence, DISPUTE_RAISE_WINDOW_HOURS

class DisputeEvidenceSerializer(serializers.ModelSerializer):
    uploaded_by_role = serializers.SerializerMethodField()
    class Meta:
        model = DisputeEvidence
        fields = [
            "id", "file_url", "file_type", "description",
            "uploaded_by_role", "created_at",
        ]
        read_only_fields = fields
    def get_uploaded_by_role(self, obj) -> str:
        return getattr(obj.uploaded_by, "role","") or ""

class DisputeSerializer(serializers.ModelSerializer):
    """Full dispute detail - returned after any mutation."""
    appointment_id = serializers.UUIDField(source="appointment.id")
    seeker_id = serializers.UUIDField(source="appointment.custmer.id")
    provider_id = serializers.UUIDField(source="appointment.provider.id")
    category = serializers.CharField(source="appointment.category.title", read_only=True)
    quoted_price = serializers.DecimalField(
        source="appointment.quoted_price",
        max_digits=10, decimal_places=2, read_only=True,
    )
    resolved_by_email = serializers.SerializerMethodField()
    evidence = DisputeEvidenceSerializer(many=True, read_only=True)

    class Meta:
        model = Dispute
        fields = [
            "id",
            "appointment_id", "seeker_id", "provider_id",
            "category", "quoted_price",
            "status", "seeker_statement", "provider_statement", "provider_statement_at", "admin_notes", "resolution", "resolution_notes", "split_percent_seeker", "resolved_by_email", "resolved_at", "provider_statement_deadline", "evidence", "created_at", "updated_at",
        ]
        read_only_fields = fields

        def get_resolved_by_email(self, obj) -> str | None:
            return obj.resolved_by.email if obj.resoved_by else None

class SubmitStatementSerializer(serializers.Serializer):
    """
    Seeker statement is captured at raise time; this is for provider
    """

    statement = serializers.CharField(max_length=3000)

    def validate(self, attrs):
        dispute:Dispute = self.context["dispute"]
        user = self.context["request"].user
        if dispute.is_terminal:
            raise serializers.ValidationError("This dispute has already been resolved.")

        if dispute.status not in (Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW):
            raise serializers.ValidationError(
                f"Statements cannot be added when dispute status is '{dispute.status}'."
            )

        if user.role == "provider":
            if dispute.provider_statement:
                raise serializers.ValidationError(
                    "You have already submitted a statement for this dispute."
                )

            if timezone.now() > dispute.provider_statement_deadline:
                raise serializers.ValidationError(
                    "The 48 hour window to submit a provider statement has passed."
                )
            
        return attrs

class UploadEvidenceSerializer(serializers.Serializer):
    """
    Either party uploads a file
    """
    file_url = serializers.URLField()
    file_type = serializers.ChoiceField(
        choices=DisputeEvidence.FileType.choices
    )
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):

        dispute:Dispute = self.context["dispute"]
        if dispute.is_terminal:
            raise serializers.ValidationError("Evidence cannot be added to a resolved dispute.")
        if dispute.status not in (Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW):
            raise serializers.ValidationError(
                 f"Evidence cannot be uploaded when dispute status is '{dispute.status}'."
            )
        return attrs

class MarkUnderReviewSerializer(serializers.Serializer):
    """Admin picks up case"""
    admin_notes = serializers.CharField(
        max_length=3000, required=False, allow_blank=True, default=""
    )

    def validate(self, attrs):
        dispute:Dispute = self.context["dispute"]
        if dispute.Status != Dispute.Status.OPEN:
            raise serializers.ValidationError(
                f"Can only mark OPEN disputes as UNDER_REVIEW. Current: '{dispute.status}'."
            )
        return attrs


class ResolveSerializer(serializers.Serializer):
    """
    Admin resolves with financial outcome.
    REFUND_SEEKER | RELEASE_PROVIDER | SPLIT
    """
    resolution = serializers.ChoiceField(choices=Dispute.Resolution.choices)
    resolution_notes = serializers.CharField(max_length=3000)
    split_percent_seeker = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=99
    )
    admin_notes = serializers.CharField(
        max_length=300,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        dispute:Dispute = self.context["dispute"]
        if dispute.is_terminal:
            raise serializers.ValidationError("This dispute is already resolved.")
        if dispute.status not in (Dispute.Status.OPEN, Dispute.Status.UNDER_REVIEW):
            raise serializers.ValidationError(
                f"Cannot resolve a dispute with status '{dispute.status}'."
            )
        if attrs["resolution"] == Dispute.Resolution.SPLIT:
            if not attrs.get("split_percent_seeker"):
                raise serializers.ValidationError(
                   {"split_percent_seeker": "Required when resolution is SPLIT."} 
                )
        return attrs

class CloserSerializer(serializers.Serializer):
    """
    Admin closes without a financial resolution (edge case: duplicate / invalid dispute).
    """
    reason = serializers.CharField(max_length=1000)

    def validate(self, attrs):
        dispute : Dispute = self.context["dispute"]
        if dispute.is_terminal:
            raise serializers.ValidationError("This dispute is already in a terminal state.")
        return attrs