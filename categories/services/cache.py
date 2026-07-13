from django.core.cache import cache

from ..constants import CATEGORY_LIST_CACHE_KEY
from ..models import Category

def invalidate_category_cache():
    cache.delete(CATEGORY_LIST_CACHE_KEY)

    cache.delete_many([
        f"skillhub:categories:detail:{slug}"
        for slug in Category.objects.values_list("slug", flat=True)
    ])