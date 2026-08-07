from django.core.cache import cache

CACHE_TTL = 60  # seconds


def _version_key(model_name, user_id):
    return f"{model_name}:cache_version:{user_id}"


def get_cache_version(model_name, user_id):
    key = _version_key(model_name, user_id)
    version = cache.get(key)
    if version is None:
        version = 1
        cache.set(key, version, None)  # never expires on its own
    return version


def bump_cache_version(model_name, user_id):
    key = _version_key(model_name, user_id)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, None)


def build_list_cache_key(model_name, user_id, query_string):
    version = get_cache_version(model_name, user_id)
    return f"{model_name}:list:{user_id}:v{version}:{query_string}"