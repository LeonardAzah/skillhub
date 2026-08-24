import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction as db_transaction
from django.db.models import Avg, Count
from django.utils import timezone

from utils.events import EventType
from notifications.publisher import publish_event

from accounts.models import ProviderProfile

from appointments.models import Appointment

from .models import Review, ProviderReviewSummary
from ._help import _round2

from .constants import (
    LOW_RATING_MIN_REVIEWS, 
    LOW_RATING_THRESHOLD, 
    PUBLIC_RATING_MIN, 
    REVIEW_WINDOW_DAYS,
    SPIKE_COUNT,
    SPIKE_WINDOW_HOURS,
    TOP_RATED_MIN_AVERAGE,
    TOP_RATED_MIN_REVIEWS
)

logger = logging.getLogger(__name__)

def check_review_eligibility(appointment, reviewer_seeker) -> None:
    """
    Raise ValueError with a descriptive message if the seeker cannot review this appointment.
    Eligibility rules
    """

    if appointment.customer != reviewer_seeker:
        raise ValueError("You can only review appointments you booked.")

    eligible_statuses = {
        Appointment.Status.CONFIRMED,
        Appointment.Status.AUTO_RELEASED,
    }

    if appointment.status not in eligible_statuses:
        raise ValueError(
            f"Reviews are only allowed for completed appointments"
            f"(CONFIRMED or AUTO_RELEASED). Current status: {appointment.status}."
        )

    terminal_at = appointment.confirmed_at or appointment.updated_at

    if terminal_at:
        deadline = terminal_at + timezone.timedelta(days=REVIEW_WINDOW_DAYS)
        if timezone.now() > deadline:
            raise ValueError(
                "The 14-day review window for this appointment has closed."
            )

    if hasattr(appointment, "review"):
        raise ValueError("You have already reviewed this appointment.")

@db_transaction.atomic
def recalculate_provider_summary(provider_id:str) -> ProviderReviewSummary:
    """
    Recompute ProviderReviewSummary from all visible reviews called asynchronously after every review event.
    """

    provider = ProviderProfile.objects.select_for_update().get(id=provider_id)
    visible = Review.objects.filter(provider=provider, is_visible=True)

    agg = visible.aggregate(
        total=Count("id"),
        avg_comm=Avg("communication_rating"),
        avg_punct=Avg("punctuality_rating"),
        avg_qual=Avg("quality_rating"),
        avg_overall=Avg("overall_rating"),
    )

    total = agg["total"] or 0
    avg_comm = _round2(agg["avg_comm"])
    avg_punct = _round2(agg["avg_punct"])
    avg_qual = _round2(agg["avg_qual"])
    avg_overall = _round2(agg["avg_overall"])

    star_dist = {"5":0, "4":0, "3":0, "2":0, "1":0}
    for review in visible.only("overall_rating"):
        bucket = int(
            review.overall_rating.quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        bucket = max(1, min(5, bucket))
        bucket = str(bucket)
        star_dist[bucket] = star_dist.get(bucket, 0) + 1

    summary, _ = ProviderReviewSummary.objects.update_or_create(
        provider=provider,
        defaults={
            "total_reviews": total,
            "avg_communication": avg_comm,
            "avg_punctuality": avg_punct,
            "avg_quality": avg_qual,
            "avg_overall": avg_overall,
            "star_distribution": star_dist,
        }
    )

    displayed_rating = avg_overall if total >= PUBLIC_RATING_MIN else Decimal("0.00")
    ProviderProfile.objects.filter(pk=provider.id).update(average_rating=displayed_rating)

    is_top_rated = (
        total >= TOP_RATED_MIN_REVIEWS and avg_overall >= TOP_RATED_MIN_AVERAGE
    )

    if total >= LOW_RATING_MIN_REVIEWS and avg_overall < LOW_RATING_THRESHOLD:
        publish_event(EventType.PROVIDER_RATING_LOW, {
            "provider_id": str(provider.id),
            "avg_overall": str(avg_overall),
            "total_reviews": total,
        })

    logger.info(
        "Provider summary recalculated",
        extra={
            "provider_id": str(provider_id),
            "total": total,
            "avg_overall": str(avg_overall),
        }
    )

    return summary