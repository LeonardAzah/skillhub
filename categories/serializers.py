"""
Serializers
───────────
CategoryChildSerializer      — lightweight child representation embedded in parent
CategorySerializer           — full public read (includes active children)
AdminCategorySerializer      — admin create / full update
AdminCategoryPatchSerializer — admin partial update (PATCH)
ProviderCategorySerializer   — provider's own categories (read)
ProviderCategoryWriteSerializer — set provider's categories (PUT)
"""
from rest_framework import serializers

from .models import Category, ProviderCategory


#  Public read 

class CategoryChildSerializer(serializers.ModelSerializer):
    """Minimal child representation embedded inside a parent's serializer."""
    icon_url = serializers.SerializerMethodField()
    provider_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = [
            "id", "title", "slug", "description",
            "icon_url", "order", "provider_count",
        ]
        read_only_fields = fields


class CategorySerializer(serializers.ModelSerializer):
    """
    Full public category representation.
    Includes active children (one level deep).
    used on GET /api/v1/categories/ and GET /api/v1/categories/{slug}/
    """
    children = serializers.SerializerMethodField()
    icon_url  = serializers.SerializerMethodField()
    parent_slug = serializers.SlugRelatedField(
        source="parent", slug_field="slug", read_only=True
    )
    provider_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = [
            "id", "title", "slug", "description", "icon_url",
            "parent_slug", "is_root", "order",
            "provider_count", "children",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_children(self, obj: Category) -> list:
        # Use prefetched `active_children` attr when available (avoids N+1)
        children = getattr(obj, "active_children", None)
        if children is None:
            children = obj.children.filter(is_active=True).order_by("order", "title")
        return CategoryChildSerializer(children, many=True, context=self.context).data

#  Admin read

class AdminCategoryListSerializer(serializers.ModelSerializer):
    full_title = serializers.ReadOnlyField()
    icon_url = serializers.ReadOnlyField(source="effective_icon_url")
    parent_slug = serializers.SerializerMethodField()
    provider_count = serializers.ReadOnlyField()

    class Meta:
        model = Category
        fields = [
            "id",
            "title",
            "full_title",
            "slug",
            "description",
            "icon_url",
            "parent_slug",
            "is_active",
            "order",
            "provider_count",
            "created_at",
            "updated_at",
        ]

    def get_parent_slug(self, obj):
        return obj.parent.slug if obj.parent else None
    
#  Admin write 

class AdminCategoryWriteSerializer(serializers.ModelSerializer):
    """
    Admin create / full update.
    POST /api/v1/admin/categories/
    """
    parent = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Category.objects.filter(is_active=True, parent__isnull=True),
        required=False,
        allow_null=True,
    )
    # Allow slug override; if omitted, auto-generated from title
    slug = serializers.SlugField(max_length=120, required=False, allow_blank=True)

    class Meta:
        model = Category
        fields = [
            "title", "slug", "description", "icon_url",
            "parent", "is_active", "order",
        ]

    def validate_slug(self, value: str) -> str:
        if not value:
            return value
        qs = Category.objects.filter(slug=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A category with this slug already exists.")
        return value

    def validate(self, attrs):
        # Enforce depth-1 constraint
        parent = attrs.get("parent") or (self.instance.parent if self.instance else None)
        if parent and parent.parent_id:
            raise serializers.ValidationError(
                {"parent": "Sub-categories cannot themselves have sub-categories (max depth: 1)."}
            )
        return attrs

    def create(self, validated_data):
        # Auto-slug from title if not supplied
        if not validated_data.get("slug"):
            validated_data["slug"] = Category._unique_slug(validated_data["title"])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Preserve slug unless the admin explicitly sends a new one
        if "slug" not in validated_data or not validated_data["slug"]:
            validated_data.pop("slug", None)
        return super().update(instance, validated_data)


class AdminCategoryPatchSerializer(AdminCategoryWriteSerializer):
    """
    PATCH — all fields optional.
    PATCH /api/v1/admin/categories/{slug}/
    """
    title = serializers.CharField(max_length=100, required=False)


# Provider category management 

class ProviderCategorySerializer(serializers.ModelSerializer):
    """Read provider's currently listed categories."""
    category = CategoryChildSerializer(read_only=True)

    class Meta:
        model = ProviderCategory
        fields = ["id", "category", "created_at"]
        read_only_fields = fields


class ProviderCategoryWriteSerializer(serializers.Serializer):
    """
    PUT /api/v1/profile/provider/categories/
    Replaces the full set of categories for the authenticated provider.

    Body: { "category_slugs": ["plumbing", "electrical"] }
    """
    category_slugs = serializers.ListField(
        child=serializers.SlugField(),
        min_length=1,
        max_length=10,
        help_text="List of active category slugs to assign to this provider.",
    )

    def validate_category_slugs(self, slugs: list) -> list:
        if len(slugs) != len(set(slugs)):
            raise serializers.ValidationError("Duplicate slugs are not allowed.")
        categories = Category.objects.active().filter(slug__in=slugs)
        if categories.count() != len(slugs):
            missing = set(slugs) - set(categories.values_list("slug", flat=True))
            raise serializers.ValidationError(
                f"Unknown or inactive category slug(s): {', '.join(sorted(missing))}"
            )
        self.context["categories"] = list(categories)
        return slugs

    def save(self):
        provider = self.context["provider"]
        categories = self.context["categories"]
        # Atomic replace: delete existing, bulk-create new
        ProviderCategory.objects.filter(provider=provider).delete()
        ProviderCategory.objects.bulk_create([
            ProviderCategory(provider=provider, category=cat)
            for cat in categories
        ])
        return categories