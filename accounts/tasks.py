from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import DeviceToken


@shared_task(
        name="accounts.tasks.prune_stale_device_tokens",
        bind=True,
)
def prune_stale_device_tokens():
    """
    Remove inactive FCM device tokens that have not been used
    for more than 90 days.
    """
    cutoff = timezone.now() - timedelta(days=90)

    deleted_count, _ = DeviceToken.objects.filter(
        last_used_at__lt=cutoff,
    ).delete()

    return deleted_count