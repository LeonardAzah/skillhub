from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Transaction, Payment
from .caching import bump_cache_version


@receiver([post_save, post_delete], sender=Transaction)
def invalidate_transaction_cache(sender, instance, **kwargs):
    bump_cache_version("transaction", instance.wallet.user_id)
    bump_cache_version("transaction", "admin")


@receiver([post_save, post_delete], sender=Payment)
def invalidate_payment_cache(sender, instance, **kwargs):
    bump_cache_version("payment", instance.user_id)
    bump_cache_version("payment", "admin")