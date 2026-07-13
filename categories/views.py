from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView, ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.settings import api_settings
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from utils.permissions import IsAdmin, IsProvider
from utils.exceptions import error_response

from .models import Category, CategoryAuditLog, ProviderCategory
from .serializers import (
    AdminCategoryPatchSerializer,
    AdminCategoryWriteSerializer,
    CategorySerializer,
    AdminCategoryListSerializer,
    ProviderCategorySerializer,
    ProviderCategoryWriteSerializer
)

from .constants import CATEGORY_LIST_CACHE_KEY, CATEGORY_LIST_CACHE_TTL
from .helper import write_audit_log, invalidate_category_cache, build_diff, refresh_provider_counts


class CategoryListCreateView(ListCreateAPIView):
    """
    GET  /api/v1/categories/   -> list active categories (public, cached)
    POST /api/v1/categories/   -> create a category (admin only)
    """
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    search_fields = [
        "title",
        "description",
    ]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsAdmin()]
        return [AllowAny()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return AdminCategoryWriteSerializer
        return CategorySerializer

    def get_queryset(self):
        return Category.objects.with_children().filter(is_active=True)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def list(self, request, *args, **kwargs):
        cache_key = (
            f"{CATEGORY_LIST_CACHE_KEY}:"
            f"{request.GET.urlencode()}"
        )

        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        response = super().list(request, *args, **kwargs)

        cache.set(
            cache_key,
            response.data,
            CATEGORY_LIST_CACHE_TTL,
        )

        return response

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category: Category = serializer.save()

        write_audit_log(category, CategoryAuditLog.Action.CREATED, request.user)
        invalidate_category_cache()

        return Response(
            {
                "success": True,
                "message": f"Category '{category.title}' created successfully.",
                "data": {"category": CategorySerializer(category, context={"request": request}).data},
            },
            status=status.HTTP_201_CREATED,
        )


class CategoryDetailView(RetrieveUpdateDestroyAPIView):
    """
    GET    /api/v1/categories/{slug}/   -> category detail (public, cached)
    PATCH  /api/v1/categories/{slug}/   -> partial update (admin only)
    DELETE /api/v1/categories/{slug}/   -> deactivate, cascades to children (admin only)
    """
    lookup_field = "slug"

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated(), IsAdmin()]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return AdminCategoryPatchSerializer
        return CategorySerializer

    def get_queryset(self):
        if self.request.method == "GET":
            return Category.objects.active().prefetch_related(
                "children__provider_categories"
            )
        return Category.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def retrieve(self, request, *args, **kwargs):
        slug = kwargs["slug"]
        cache_key = f"skillhub:categories:detail:{slug}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(
                {
                    "success": True,
                    "message": "Category retrieved successfully.",
                    "data": cached_data,
                }
            )

        try:
            category = self.get_queryset().get(slug=slug)
        except Category.DoesNotExist:
            return error_response("Category not found.", status.HTTP_404_NOT_FOUND)

        category_data = CategorySerializer(category, context={"request": request}).data
        cache.set(cache_key, category_data, CATEGORY_LIST_CACHE_TTL)

        return Response(
            {
                "success": True,
                "message": "Category retrieved successfully.",
                "data": category_data,
            }
        )

    def update(self, request, *args, **kwargs):
        try:
            category = Category.objects.get(slug=kwargs["slug"])
        except Category.DoesNotExist:
            return error_response("Category not found.", status.HTTP_404_NOT_FOUND)

        # Snapshot before update for the diff
        before = {
            "title":       category.title,
            "description": category.description,
            "icon_url":    category.icon_url,
            "is_active":   category.is_active,
            "order":       category.order,
            "parent":      category.parent.slug if category.parent else None,
        }

        serializer = self.get_serializer(category, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        category = serializer.save()

        after = {
            "title":       category.title,
            "description": category.description,
            "icon_url":    category.icon_url,
            "is_active":   category.is_active,
            "order":       category.order,
            "parent":      category.parent.slug if category.parent else None,
        }
        diff = build_diff(before, after)

        write_audit_log(category, CategoryAuditLog.Action.UPDATED, request.user, diff)
        invalidate_category_cache()

        return Response(
            {
                "success": True,
                "message": f"Category '{category.title}' updated successfully.",
                "data": {"category": CategorySerializer(category, context={"request": request}).data},
            }
        )

    def destroy(self, request, *args, **kwargs):
        try:
            category = Category.objects.get(slug=kwargs["slug"])
        except Category.DoesNotExist:
            return error_response("Category not found.", status.HTTP_404_NOT_FOUND)

        if not category.is_active:
            return error_response("Category is already inactive.", status.HTTP_400_BAD_REQUEST)

        # Deactivate children too — prevents orphaned active subcategories
        child_slugs = list(category.children.filter(is_active=True).values_list("slug", flat=True))
        category.children.filter(is_active=True).update(is_active=False)

        category.is_active = False
        category.save(update_fields=["is_active", "updated_at"])

        write_audit_log(category, CategoryAuditLog.Action.DEACTIVATED, request.user)
        invalidate_category_cache()

        return Response(
            {
                "success": True,
                "message": f"Category '{category.title}' has been deactivated.",
                "data": {"deactivated_children": child_slugs},
            },
            status=status.HTTP_200_OK,
        )


class AdminCategoryActivateView(APIView):
    """
    POST /api/v1/admin/categories/{slug}/activate/
    Re-activate a previously deactivated category.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, slug: str):
        try:
            category = Category.objects.get(slug=slug)
        except Category.DoesNotExist:
            return error_response("Category not found.", status.HTTP_404_NOT_FOUND)

        if category.is_active:
            return error_response("Category is already active.", status.HTTP_400_BAD_REQUEST)

        # If this is a child, ensure the parent is also active
        if category.parent and not category.parent.is_active:
            return error_response(
                f"Parent category '{category.parent.title}' must be activated first.",
                status.HTTP_400_BAD_REQUEST,
            )

        category.is_active = True
        category.save(update_fields=["is_active", "updated_at"])

        write_audit_log(category, CategoryAuditLog.Action.ACTIVATED, request.user)
        invalidate_category_cache()

        return Response(
            {
                "success": True,
                "message": f"Category '{category.title}' activated successfully.",
                "data": {"category": CategorySerializer(category, context={"request": request}).data},
            },
            status=status.HTTP_200_OK,
        )

class AdminCategoryListView(ListAPIView):
    """
    GET /api/v1/admin/categories/
    Admin view of ALL categories including inactive ones.
    Supports ?is_active=true/false and ?parent=<slug> query params.
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = AdminCategoryListSerializer

    def get_queryset(self):
        qs = Category.objects.all().select_related("parent").order_by("order", "title")

        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")

        parent_slug = self.request.query_params.get("parent")
        if parent_slug == "null":
            qs = qs.filter(parent__isnull=True)
        elif parent_slug:
            qs = qs.filter(parent__slug=parent_slug)

        return qs


class ProviderCategoryListView(APIView):
    """
    GET /api/v1/providers
    List the authenticated provider's current service categories.
    """
    permission_classes = [IsAuthenticated, IsProvider]

    def get(self, request):
        provider = request.user.provider_profile
        pcs = (
            ProviderCategory.objects
            .filter(provider=provider)
            .select_related("category__parent")
            .order_by("category__order", "category__title")
        )
        return Response(ProviderCategorySerializer(pcs, many=True).data)


class ProviderCategoryUpdateView(APIView):
    """
    PUT /api/v1/profile/provider/categories/
    Replace the authenticated provider's full set of service categories.

    Body: { "category_slugs": ["plumbing", "electrical"] }
    """
    permission_classes = [IsAuthenticated, IsProvider]

    def put(self, request):
        provider = request.user.provider_profile
        serializer = ProviderCategoryWriteSerializer(
            data=request.data,
            context={"request": request, "provider": provider},
        )
        serializer.is_valid(raise_exception=True)
        categories = serializer.save()

        # Update cached provider_count for affected categories
        refresh_provider_counts(
            [c.slug for c in categories]
            + list(
                ProviderCategory.objects
                .filter(provider=provider)
                .values_list("category__slug", flat=True)
            )
        )
        invalidate_category_cache()

        # Return current state
        pcs = (
            ProviderCategory.objects
            .filter(provider=provider)
            .select_related("category__parent")
            .order_by("category__order", "category__title")
        )
        return Response(ProviderCategorySerializer(pcs, many=True).data)