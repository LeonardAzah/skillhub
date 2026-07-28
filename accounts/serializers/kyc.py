from rest_framework import serializers

from ..models import (User, KYCDocument)

class KYCSubmitSerializer(serializers.ModelSerializer):
    """Submit KYC documents."""

    class Meta:
        model = KYCDocument
        fields = ["document_type", "decument_side", "file"]

    def validate(self, attrs):
        user: User = self.context["request"].user

        if user.role == User.Role.PROVIDER:
            doc_side = attrs.get("document_side")
            if doc_side not in [
                KYCDocument.DocumentSide.SELFIE,
                KYCDocument.DocumentSide.ADDRESS_PROOF,
                KYCDocument.DocumentSide.FRONT,
                KYCDocument.DocumentSide.BACK,
                KYCDocument.DocumentSide.SINGLE,

            ]: raise serializers.ValidationError("Invalid document side for provider KYC")
        return attrs

    def create(self, validated_data):
        validated_data["user"] = self.context["request"].user
        return super().create(validated_data)

class KYCStatusSerializer(serializers.Serializer):
    """GET /profile/verify/status"""
    is_verified = serializers.BooleanField()
    documents = serializers.SerializerMethodField()

    def get_documents(self, user:User):
        docs = user.kyc_documents.all().order_by("-created_at")
        return [
            {
                "id": str(doc.id),
                "document_type": doc.document_type,
                "document_side": doc.document_side,
                "status": doc.status,
                "rejection_reason": doc.rejection_reason,
                "created_at": doc.created_at.isoformat(),
            }
            for doc in docs
        ]

class KYCDocumentSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    user_id = serializers.CharField(source="user.id", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = KYCDocument
        fields = [
            "id",
            "user_id",
            "user_email",
            "document_type",
            "document_side",
            "status",
            "created_at",
        ]


class KYCDocumentDetailSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    user_id = serializers.CharField(source="user.id", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = KYCDocument
        fields = [
            "id",
            "user_id",
            "user_email",
            "user_username",
            "document_type",
            "document_side",
            "status",
            "file_url",
            "rejection_reason", 
            "reviewed_by",      
            "reviewed_at",        
            "created_at",
            "updated_at",
        ]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None