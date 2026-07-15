from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models import PortfolioItem, ProviderProfile, PortfolioItem, PortfolioImage
from ..serializers import PortfolioItemSerializer, PortfolioImageSerializer
from utils.permissions import IsProvider
from utils.storage import delete_remote_asset
from ..constants import MAX_IMAGES_PER_PORTFOLIO_ITEM
from utils.exceptions import error_response


class ProviderPortfolioListView(APIView):
    """
    GET /api/v1/portfolio/provider/{provider_id}/
    Public — fetch all portfolio items for one specific provider.
    Owner viewing their own portfolio also sees unpublished drafts.
    """
    permission_classes = [AllowAny]

    def get(self, request, provider_id):
        try:
            provider = ProviderProfile.objects.get(id=provider_id)
        except ProviderProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "Provider not found.", "errors": {}},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_owner = bool(
            request.user.is_authenticated
            and getattr(request.user, "role", None) == "provider"
            and hasattr(request.user, "provider_profile")
            and request.user.provider_profile.id == provider.id
        )

        queryset = provider.portfolio_items.prefetch_related("images")
        if not is_owner:
            queryset = queryset.filter(is_published=True)
        queryset = queryset.order_by("display_order", "-completed_on", "-created_at")

        serializer = PortfolioItemSerializer(queryset, many=True, context={"request": request})
        return Response(
            {"success": True, "message": "Portfolio retrieved.", "data": serializer.data}
        )


class PortfolioItemCreateView(APIView):
    """
    POST /api/v1/portfolio/
    Only an authenticated provider can create — always under their own profile.
    """
    permission_classes = [IsProvider]

    def post(self, request):
        serializer = PortfolioItemSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response(
                {"success": False, "message": "Validation failed.", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance = serializer.save(provider=request.user.provider_profile)
        return Response(
            {
                "success": True,
                "message": "Portfolio item created.",
                "data": PortfolioItemSerializer(instance, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class PortfolioItemDetailView(APIView):
    """
    PATCH /api/v1/portfolio/{id}/    — owner only, partial update
    DELETE /api/v1/portfolio/{id}/   — owner only
    """
    permission_classes = [IsProvider]

    def _get_owned_object(self, request, item_id):
        instance = get_object_or_404(PortfolioItem, id=item_id)
        if instance.provider.user_id != request.user.id:
            return None
        return instance

    def patch(self, request, item_id):
        instance = self._get_owned_object(request, item_id)
        if instance is None:
            return Response(
                {"success": False, "message": "You do not own this portfolio item.", "errors": {}},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = PortfolioItemSerializer(
            instance, data=request.data, partial=True, context={"request": request}
        )
        if not serializer.is_valid():
            return Response(
                {"success": False, "message": "Validation failed.", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        updated = serializer.save()
        return Response(
            {
                "success": True,
                "message": "Portfolio item updated.",
                "data": PortfolioItemSerializer(updated, context={"request": request}).data,
            }
        )

    def delete(self, request, item_id):
        instance = self._get_owned_object(request, item_id)
        if instance is None:
            return Response(
                {"success": False, "message": "You do not own this portfolio item.", "errors": {}},
                status=status.HTTP_403_FORBIDDEN,
            )

        public_ids = list(
            instance.images.exclude(public_id="").values_list("public_id", flat=True)
        )
        if instance.cover_image_public_id:
            public_ids.append(instance.cover_image_public_id)

        with transaction.atomic():
            instance.delete()
            if public_ids:
                transaction.on_commit(lambda: self._cleanup_assets(public_ids))

        return Response(
            {"success": True, "message": "Portfolio item deleted.", "data": {}},
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _cleanup_assets(public_ids):
        import logging
        logger = logging.getLogger(__name__)
        for public_id in public_ids:
            try:
                delete_remote_asset(public_id)
            except Exception:
                logger.exception("Failed to delete remote asset %s", public_id)


class PortfolioItemTogglePublishView(APIView):
    """POST /api/v1/portfolio/{id}/toggle-publish/ — owner only."""
    permission_classes = [IsProvider]

    def post(self, request, item_id):
        instance = get_object_or_404(PortfolioItem, id=item_id)
        if instance.provider.user_id != request.user.id:
            return Response(
                {"success": False, "message": "You do not own this portfolio item.", "errors": {}},
                status=status.HTTP_403_FORBIDDEN,
            )
        instance.is_published = not instance.is_published
        instance.save(update_fields=["is_published", "updated_at"])
        return Response(
            {
                "success": True,
                "message": "Publish status toggled.",
                "data": PortfolioItemSerializer(instance, context={"request": request}).data,
            }
        )


class PortfolioItemToggleFeaturedView(APIView):
    """POST /api/v1/portfolio/{id}/toggle-featured/ — owner only."""
    permission_classes = [IsProvider]

    def post(self, request, item_id):
        instance = get_object_or_404(PortfolioItem, id=item_id)
        if instance.provider.user_id != request.user.id:
            return Response(
                {"success": False, "message": "You do not own this portfolio item.", "errors": {}},
                status=status.HTTP_403_FORBIDDEN,
            )
        instance.is_featured = not instance.is_featured
        instance.save(update_fields=["is_featured", "updated_at"])
        return Response(
            {
                "success": True,
                "message": "Featured status toggled.",
                "data": PortfolioItemSerializer(instance, context={"request": request}).data,
            }
        )
    
class PortfolioItemImageAddView(APIView):
    """
    POST /api/v1/portfolio/<item_id>/images/
    Adds one or more images to an existing portfolio item's gallery.
    Owner only.
    """
    permission_classes = [IsProvider]

    def _get_owned_item(self, request, item_id):
        instance = get_object_or_404(
            PortfolioItem.objects.select_related("provider"), id=item_id
        )
        if instance.provider.user_id != request.user.id:
            return None
        return instance

    def post(self, request, item_id):
        item = self._get_owned_item(request, item_id)
        if item is None:
            return error_response(message="You do not own this portfolio item.", status_code=status.HTTP_403_FORBIDDEN)
                   

        # Accept either a single image object or a list of them
        payload = request.data
        many = isinstance(payload, list)

        existing_count = item.images.count()
        incoming_count = len(payload) if many else 1
        if existing_count + incoming_count > MAX_IMAGES_PER_PORTFOLIO_ITEM:
            return error_response(message=f"This portfolio item can have at most "
            f"{MAX_IMAGES_PER_PORTFOLIO_ITEM} images "
            f"(currently has {existing_count}).", status_code=status.HTTP_400_BAD_REQUEST,)

        serializer = PortfolioImageSerializer(data=payload, many=many)
        if not serializer.is_valid():
            return error_response(
                message="Validation failed.",
                status_code=status.HTTP_400_BAD_REQUEST,
                data=serializer.errors
            )
            
        if many:
            # Preserve caller-provided display_order, or append after existing images
            base_order = existing_count
            instances = [
                PortfolioImage(portfolio_item=item, **{**data, "display_order": data.get("display_order", base_order + i)})
                for i, data in enumerate(serializer.validated_data)
            ]
            created = PortfolioImage.objects.bulk_create(instances)
            data = PortfolioImageSerializer(created, many=True).data
        else:
            data_dict = dict(serializer.validated_data)
            data_dict.setdefault("display_order", existing_count)
            instance = PortfolioImage.objects.create(portfolio_item=item, **data_dict)
            data = PortfolioImageSerializer(instance).data

        return Response(
            {"success": True, "message": "Image(s) added.", "data": data},
            status=status.HTTP_201_CREATED,
        )
    
class PortfolioImageDetailView(APIView):
    """
    PATCH  /api/v1/portfolio/images/<image_id>/ — edit caption/display_order etc.
    DELETE /api/v1/portfolio/images/<image_id>/ — remove image + cleanup storage
    Owner only.
    """
    permission_classes = [IsProvider]

    def _get_owned_image(self, request, image_id):
        image = get_object_or_404(
            PortfolioImage.objects.select_related("portfolio_item__provider"),
            id=image_id,
        )
        if image.portfolio_item.provider.user_id != request.user.id:
            return None
        return image

    def patch(self, request, image_id):
        image = self._get_owned_image(request, image_id)
        if image is None:
            return Response(
                {"success": False, "message": "You do not own this image.", "errors": {}},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = PortfolioImageSerializer(image, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(
                {"success": False, "message": "Validation failed.", "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer.save()
        return Response({"success": True, "message": "Image updated.", "data": serializer.data})

    def delete(self, request, image_id):
        image = self._get_owned_image(request, image_id)
        if image is None:
            return Response(
                {"success": False, "message": "You do not own this image.", "errors": {}},
                status=status.HTTP_403_FORBIDDEN,
            )

        public_id = image.public_id
        with transaction.atomic():
            image.delete()
            if public_id:
                transaction.on_commit(lambda: self._cleanup_asset(public_id))

        return Response({"success": True, "message": "Image removed.", "data": {}})

    @staticmethod
    def _cleanup_asset(public_id):
        import logging
        logger = logging.getLogger(__name__)
        try:
            delete_remote_asset(public_id)
        except Exception:
            logger.exception("Failed to delete remote asset %s", public_id)
