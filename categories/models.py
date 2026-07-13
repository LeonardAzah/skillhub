from django.db import models

"""
Models
──────
Category          — service category tree (parent / child)
ProviderCategory  — M2M through-table linking providers to categories
                    with an explicit join so we can add metadata later
CategoryAuditLog  — immutable log of every admin mutation
"""
import uuid

from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class CategoryManager(models.Manager):
    """Custom manager with helpers used across views and serializers."""

    def active(self):
        """Active, non-deleted categories."""
        return self.get_queryset().filter(is_active=True)

    def roots(self):
        """Top-level categories (no parent)."""
        return self.active().filter(parent__isnull=True)

    def with_children(self):
        """Roots prefetched with their active children — used on list endpoint."""
        return (
            self.roots()
            .prefetch_related(
                models.Prefetch(
                    "children",
                    queryset=self.active().order_by("order", "title"),
                    to_attr="active_children",
                )
            )
            .order_by("order", "title")
        )


class Category(models.Model):
    """
    Supports one level of nesting (parent / child) sufficient for the
    default taxonomy.  The parent FK is nullable; a null parent means
    this is a root category.

    Slug is auto-derived from title on first save and is unique.
    Admins may override it; subsequent title changes do NOT auto-update
    the slug to preserve stable public URLs.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(
        _("title"),
        max_length=100,
        help_text=_("Human-readable name, e.g. 'Plumbing'."),
    )
    slug = models.SlugField(
        _("slug"),
        max_length=120,
        unique=True,
        help_text=_("URL-safe identifier, auto-generated from title."),
    )
    description = models.TextField(
        _("description"),
        blank=True,
        default="",
        help_text=_("Optional category description shown to users."),
    )
    icon_url = models.URLField(
        _("icon URL"),
        blank=True,
        default="",
        help_text=_("S3 URL for category icon used in the mobile app."),
    )
    

    # Hierarchy
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        help_text=_("Optional parent for sub-categories."),
    )

    #  Admin control
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Inactive categories are hidden from public endpoints."),
        db_index=True,
    )
    order = models.PositiveSmallIntegerField(
        _("display order"),
        default=0,
        help_text=_("Lower values appear first. 0 = default ordering by title."),
    )

    # Provider stats (denormalised for fast discovery screens)
    provider_count = models.PositiveIntegerField(
        _("provider count"),
        default=0,
        help_text=_("Cached count of verified providers offering this category."),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CategoryManager()

    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ["order", "title"]
        indexes = [
            models.Index(fields=["is_active", "parent"]),
            models.Index(fields=["slug"]),
        ]

    # Lifecycle

    def save(self, *args, **kwargs):
        # Auto-generate slug from title only on creation
        if not self.slug:
            self.slug = self._unique_slug(self.title)
        super().save(*args, **kwargs)

    @staticmethod
    def _unique_slug(title: str) -> str:
        """Generate a slug from title, appending a counter if already taken."""
        base = slugify(title)[:110]
        candidate = base
        counter = 1
        while Category.objects.filter(slug=candidate).exists():
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    #  Validation

    def clean(self):
        from django.core.exceptions import ValidationError
        # Prevent circular hierarchy: a category cannot be its own ancestor
        if self.parent_id:
            if str(self.parent_id) == str(self.pk):
                raise ValidationError({"parent": _("A category cannot be its own parent.")})
            if self._is_descendant_of(self.parent_id):
                raise ValidationError({"parent": _("Circular hierarchy detected.")})
        # Limit depth to 1 (parent → child only, no grandchildren)
        if self.parent and self.parent.parent_id:
            raise ValidationError({"parent": _("Sub-categories cannot themselves have sub-categories (max depth: 1).")})

    def _is_descendant_of(self, potential_ancestor_id) -> bool:
        """Check if potential_ancestor_id is a descendant of this category."""
        children = list(self.children.values_list("id", flat=True))
        if str(potential_ancestor_id) in [str(c) for c in children]:
            return True
        return False

    #  Properties

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def full_title(self) -> str:
        """'Electrical > Low Voltage' style display string."""
        if self.parent:
            return f"{self.parent.title} › {self.title}"
        return self.title

    def __str__(self):
        return self.full_title


class ProviderCategory(models.Model):
    """
    Explicit M2M through-table between ProviderProfile and Category.
    Allows future addition of metadata (e.g. years of experience in this
    specific category, portfolio images per category).

    SRS §5.2 — services_offered M2M to Category.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        "accounts.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="provider_categories",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="provider_categories",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("provider category")
        verbose_name_plural = _("provider categories")
        unique_together = [("provider", "category")]

    def __str__(self):
        return f"{self.provider} — {self.category}"


class CategoryAuditLog(models.Model):
    """
    Immutable audit trail for every admin mutation on a category.
    Retained for compliance and admin accountability.
    """

    class Action(models.TextChoices):
        CREATED    = "created",    _("Created")
        UPDATED    = "updated",    _("Updated")
        ACTIVATED  = "activated",  _("Activated")
        DEACTIVATED= "deactivated",_("Deactivated")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    category_slug = models.SlugField(
        max_length=120,
        help_text=_("Preserved even if the category is later deleted."),
    )
    action = models.CharField(max_length=15, choices=Action.choices)
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="category_audit_logs",
    )
    diff = models.JSONField(
        default=dict,
        help_text=_("Fields changed: {field: [old_value, new_value]}."),
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("category audit log")
        verbose_name_plural = _("category audit logs")
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.action}] {self.category_slug} by {self.actor}"