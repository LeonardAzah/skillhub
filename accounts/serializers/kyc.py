from django.db import IntegrityError
from rest_framework import serializers

from ..models import User, KYCSubmission, KYCDocument


class KYCDocumentInputSerializer(serializers.Serializer):
    """One uploaded file, as sent inside a submission payload."""

    document_type = serializers.ChoiceField(choices=KYCDocument.DocumentType.choices)
    document_side = serializers.ChoiceField(
        choices=KYCDocument.DocumentSide.choices, required=False, allow_blank=True, default=""
    )
    file_url = serializers.URLField(max_length=500)

    def validate(self, attrs):
        doc_type = attrs["document_type"]
        side = attrs.get("document_side", "")

        is_id_doc = doc_type in KYCDocument.ID_DOCUMENT_TYPES
        if is_id_doc and not side:
            raise serializers.ValidationError(
                {"document_side": "Required for passport/national_id/driver_license."}
            )
        if not is_id_doc and side:
            raise serializers.ValidationError(
                {"document_side": "Must be left blank for selfie/location_plan."}
            )
        return attrs


class KYCDocumentSerializer(serializers.ModelSerializer):
    """Read-only representation of a stored document, nested in a submission."""

    id = serializers.CharField(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = KYCDocument
        fields = ["id", "document_type", "document_side", "file_url", "created_at"]

    def get_file_url(self, obj):
        # Swap this for your actual signed-URL generator (S3 presign /
        # Cloudinary signed delivery URL) rather than exposing the raw
        # stored URL directly.
        request = self.context.get("request")
        if request is None:
            return obj.file_url
        return request.build_absolute_uri(obj.file_url)


REQUIRED_DOCUMENT_TYPES = {
    KYCDocument.DocumentType.SELFIE,
    KYCDocument.DocumentType.LOCATION_PLAN,
}


class KYCSubmissionCreateSerializer(serializers.ModelSerializer):
    """submit (or re-submit) a full KYC application."""

    documents = KYCDocumentInputSerializer(many=True, write_only=True)

    class Meta:
        model = KYCSubmission
        fields = [
            "full_name",
            "date_of_birth",
            "nationality",
            "phone_number",
            "address",
            "documents",
        ]

    def validate_documents(self, documents):
        if not documents:
            raise serializers.ValidationError("At least one document is required.")

        types = [d["document_type"] for d in documents]
        if len(types) != len(set((d["document_type"], d["document_side"]) for d in documents)):
            raise serializers.ValidationError("Duplicate document slot submitted.")

        has_id_doc = any(t in KYCDocument.ID_DOCUMENT_TYPES for t in types)
        if not has_id_doc:
            raise serializers.ValidationError(
                "At least one identity document (passport/national_id/driver_license) is required."
            )
        missing = REQUIRED_DOCUMENT_TYPES - set(types)
        if missing:
            raise serializers.ValidationError(
                f"Missing required document(s): {', '.join(sorted(missing))}."
            )
        return documents

    def validate(self, attrs):
        user: User = self.context["request"].user

        has_active = KYCSubmission.objects.filter(
            user=user, status__in=[KYCSubmission.Status.PENDING, KYCSubmission.Status.APPROVED]
        ).exists()
        if has_active:
            raise serializers.ValidationError(
                "You already have a KYC submission that is pending or approved. "
                "You can only submit again after a rejection."
            )

        if user.role == User.Role.PROVIDER:
            # Provider-specific rules can plug in here, e.g. requiring a
            # particular document type, if that's still needed.
            pass

        return attrs

    def create(self, validated_data):
        documents_data = validated_data.pop("documents")
        user = self.context["request"].user

        try:
            submission = KYCSubmission.objects.create(user=user, **validated_data)
        except IntegrityError:
            # Race condition: two submits landed at once and the DB
            # constraint caught what the earlier .exists() check missed.
            raise serializers.ValidationError(
                "You already have a KYC submission that is pending or approved."
            )

        KYCDocument.objects.bulk_create(
            [KYCDocument(submission=submission, **doc) for doc in documents_data]
        )
        return submission


class KYCSubmissionSerializer(serializers.ModelSerializer):
    """Full read representation: submission + its documents."""

    id = serializers.CharField(read_only=True)
    documents = KYCDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = KYCSubmission
        fields = [
            "id",
            "full_name",
            "date_of_birth",
            "nationality",
            "phone_number",
            "address",
            "status",
            "rejection_reason",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
            "documents",
        ]


class KYCStatusSerializer(serializers.Serializer):
    """GET /profile/verify/status"""

    is_verified = serializers.BooleanField()
    submission = serializers.SerializerMethodField()

    def get_submission(self, user: User):
        latest = user.kyc_submissions.order_by("-created_at").first()
        if latest is None:
            return None
        return KYCSubmissionSerializer(latest, context=self.context).data


class KYCSubmissionListSerializer(serializers.ModelSerializer):
    """Lightweight row for an admin's review queue (no documents payload)."""

    id = serializers.CharField(read_only=True)
    user_id = serializers.CharField(source="user.id", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = KYCSubmission
        fields = [
            "id",
            "user_id",
            "user_email",
            "full_name",
            "status",
            "created_at",
        ]


class KYCSubmissionDetailSerializer(serializers.ModelSerializer):
    """Full detail for an admin reviewing one submission, documents included."""

    id = serializers.CharField(read_only=True)
    user_id = serializers.CharField(source="user.id", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    documents = KYCDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = KYCSubmission
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_username",
            "full_name",
            "date_of_birth",
            "nationality",
            "phone_number",
            "address",
            "status",
            "rejection_reason",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
            "documents",
        ]
