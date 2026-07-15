import logging
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from ..models import PortfolioItem, PortfolioImage
from ..constants import MAX_PORTFOLIO_ITEMS_PER_PROVIDER 
from utils.storage import delete_remote_asset  # your Cloudinary/S3 wrapper

logger = logging.getLogger(__name__)


class PortfolioImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioImage
        fields = [
            "id", "url", "public_id", "media_type", "thumbnail_url", "file_size_bytes", "caption",
            "display_order", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class PortfolioItemListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioItem
        fields = [
            "id",
            "title",
            "category",
            "cover_image_url",
            "is_featured",
            "completed_on",
            "display_order",
        ]

class PortfolioItemSerializer(serializers.ModelSerializer):
    # Read-only nested representation only — images are managed exclusively
    # via /portfolio/<item_id>/images/ (add) and /portfolio/images/<id>/
    # (edit caption / remove), never through this serializer's write path.
    images = PortfolioImageSerializer(many=True, read_only=True)

    class Meta:
        model = PortfolioItem
        fields = [
            "id",
            "provider",
            "title",
            "description",
            "category",
            "completed_on",
            "client_name",
            "cover_image_url",
            "cover_image_public_id",
            "is_featured",
            "is_published",
            "display_order",
            "images",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "provider", "created_at", "updated_at"]

    def validate(self, attrs):
        if self.instance is None:
            request = self.context["request"]
            provider = request.user.provider_profile
            existing_count = PortfolioItem.objects.filter(provider=provider).count()
            if existing_count >= MAX_PORTFOLIO_ITEMS_PER_PROVIDER:
                raise serializers.ValidationError(
                    {
                        "non_field_errors": [
                            f"You have reached the maximum of "
                            f"{MAX_PORTFOLIO_ITEMS_PER_PROVIDER} portfolio items."
                        ]
                    }
                )
        return attrs

    def create(self, validated_data):
        instance = PortfolioItem(**validated_data)
        try:
            instance.save()
        except DjangoValidationError as e:
            raise serializers.ValidationError(self._django_error_to_dict(e))
        return instance

    def update(self, instance, validated_data):
        old_cover_public_id = None
        if "cover_image_public_id" in validated_data:
            if instance.cover_image_public_id != validated_data["cover_image_public_id"]:
                old_cover_public_id = instance.cover_image_public_id

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        try:
            instance.save()
        except DjangoValidationError as e:
            raise serializers.ValidationError(self._django_error_to_dict(e))

        if old_cover_public_id:
            transaction.on_commit(lambda: self._cleanup_asset(old_cover_public_id))

        return instance

    @staticmethod
    def _cleanup_asset(public_id):
        try:
            delete_remote_asset(public_id)
        except Exception:
            logger.exception("Failed to delete remote asset %s", public_id)

    @staticmethod
    def _django_error_to_dict(exc):
        if hasattr(exc, "message_dict"):
            return exc.message_dict
        return {"non_field_errors": exc.messages}

