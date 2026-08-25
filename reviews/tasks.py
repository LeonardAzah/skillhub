import logging

from celery import shared_task

from django.utils import timezone

from .models import Review
from .constants import REVIEW_WINDOW_DAYS

from utils.events import EventType
from notifications.publisher import publish_event
from appointments.models import Appointment

logger = logging.getLogger(__name__)


@shared_task(
    name="reviews.tasks.recalculate_provider_rating",
    bind=True,
    max_retries=5,
    default_retry_delay=10,
    queue="default",
)
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


@shared_task(
        name="reviews.tasks.send_review_reminders",
        bind=True,
        max_retries=3,
        default_retry_delay=60,
        queue="default",  
)
def send_review_reminders(self) -> dict:
    """
    Send push reminders at T+3 and T+10 days  for CONFIRMED/AUTO_RELEASED appointments
    where no review has been submitted.
    Runs every 6 hours via Celery Beat.
    """

    now = timezone.now()
    sent_3d = 0
    sent_10d = 0

    # Find all terminal appointments within the review window
    terminal_statuses = [
        Appointment.Status.CONFIRMED,
        Appointment.Status.AUTO_RELEASED,
    ]
    eligible = Appointment.objects.filter(
        status__in=terminal_statuses,
        confirmed_at__isnull=False,
    ).exclude(
        review__isnull=False #already has a review
    ).select_related("customer", "provider")

    for apt in eligible:
        terminal_at = apt.confirmed_at
        days_elapsed = (now - terminal_at).days

        if days_elapsed > REVIEW_WINDOW_DAYS:
            continue

        base_payload = {
            "appointment_id": str(apt.id),
            "seeker_id": str(apt.customer.id),
            "provider_id": str(apt.provider.id),
            "provider_name": apt.provider.full_name or "",
        }

        # T+3 reminder
        if 3 <= days_elapsed < 4:
            publish_event(EventType.REVIEW_REMINDER_3D, base_payload)
            sent_3d += 1

        # T+10 reminder
        elif 10 <= days_elapsed < 11:
            publish_event(EventType.REVIEW_REMINDER_10D, base_payload)
            sent_10d += 1

    logger.info(
        "Review reminders sent",
        extra={"sent_3d": sent_3d, "sent_10d": sent_10d}
    )

    return {"status": "ok", "sent_3d": sent_3d, "sent_10d": sent_10d}
