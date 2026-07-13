from django.core.cache import cache

from .models import Category, CategoryAuditLog, ProviderCategory

from .constants import CATEGORY_LIST_CACHE_KEY

def invalidate_category_cache():
    """Bust the category list cache after any admin mutation."""
    cache.delete(CATEGORY_LIST_CACHE_KEY)
    # Also bust individual detail caches (pattern delete via prefix)
    cache.delete_many([
        f"skillhub:categories:detail:{slug}"
        for slug in Category.objects.values_list("slug", flat=True)
    ])


def write_audit_log(
    category: Category,
    action: str,
    actor,
    diff: dict | None = None,
):
    CategoryAuditLog.objects.create(
        category=category,
        category_slug=category.slug,
        action=action,
        actor=actor,
        diff=diff or {},
    )


def build_diff(old_data: dict, new_data: dict) -> dict:
    """Return {field: [old_value, new_value]} for changed fields."""
    diff = {}
    for key in set(old_data) | set(new_data):
        old_val = old_data.get(key)
        new_val = new_data.get(key)
        if str(old_val) != str(new_val):
            diff[key] = [old_val, new_val]
    return diff


def refresh_provider_counts(slugs: list[str]):
    """
    Recompute provider_count for the given category slugs.
    Called after provider categories change.
    """
    if not slugs:
        return
    categories = Category.objects.filter(slug__in=set(slugs))
    for cat in categories:
        count = ProviderCategory.objects.filter(
            category=cat,
            provider__is_verified=True,
        ).count()
        Category.objects.filter(pk=cat.pk).update(provider_count=count)