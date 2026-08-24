import logging

from celery import shared_task

from django.utils import timezone

from .models import Review

from utils.events import EventType
from notifications.publisher import publish_event
from appointments.models import Appointment

logger = logging.getLogger(__name__)

def recalculate_provider_rating(self, provider_id:str) -> dict:
    """
    Recompute ProviderReviewSummary within 30 s of review event.
    Enqueued by the review views after every create / edit / remove action.
    """

    from .services import recalculate_provider_summary
    try:
        summary = recalculate_provider_summary(provider_id=provider_id)
        return {
            "status":       "ok",
            "provider_id":  str(provider_id),
            "avg_overall":  str(summary.avg_overall),
            "total_reviews":summary.total_reviews,
        }
    except Exception as exc:
        logger.exception(
            "Rating recalculation failed",
            extra={
                "provider_id": provider_id,
                "error": str(exc),
            }
        )
        raise self.retry(exc=exc)




