"""
Private utilities shared across view modules.
"""


def _frontend_url() -> str:
    from django.conf import settings
    return getattr(settings, "FRONTEND_URL", "http://localhost:3000")


def _setting(key: str, default):
    from django.conf import settings
    return getattr(settings, key, default)



