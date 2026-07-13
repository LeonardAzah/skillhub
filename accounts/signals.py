from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache_utils import bump_cache_version
from .models import ProviderCategory, ProviderProfile

@receiver([post_save, post_delete], sender=ProviderProfile)
def invalidate_on_provider_change(sender, **kwargs):
    bump_cache_version()


@receiver([post_save, post_delete], sender=ProviderCategory)
def invalidate_on_category_link_change(sender, **kwargs):
    bump_cache_version()