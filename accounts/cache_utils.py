
from .constants import PROVIDER_LIST_CACHE_KEY
from django.core.cache import cache


def get_cache_version():
    version = cache.get(PROVIDER_LIST_CACHE_KEY)
    if version is None:
        version = 1
        cache.set(PROVIDER_LIST_CACHE_KEY, version, None)
    return version


def bump_cache_version():
    try:
        cache.incr(PROVIDER_LIST_CACHE_KEY)
    except ValueError:
        # Key expired/missing between get and incr -- reset it.
        cache.set(PROVIDER_LIST_CACHE_KEY, 1, None)