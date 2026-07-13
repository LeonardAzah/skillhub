import redis
from django.conf import settings

# Reuses a connection pool instead of opening a new connection per call
orders_redis = redis.Redis.from_url(
    settings.ORDERS_REDIS_URL,
    decode_responses=True,  # get str back instead of bytes
)