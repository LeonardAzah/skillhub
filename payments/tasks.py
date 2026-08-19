"""
BoloConnect — apps/payments/tasks.py

Celery tasks that listen to appointment domain events and
trigger the corresponding financial operations.

These tasks are the integration point between the appointments
and payments modules — they close the escrow lifecycle loop.
"""
import logging
from celery import shared_task

from decimal import Decimal
from appointments.models import Appointment
from .services import refund_escrow

logger = logging.getLogger(__name__)


@shared_task(
    name="payments.tasks.on_appointment_created",
    bind=True, max_retries=3, default_retry_delay=30,
    queue="payments",
)
def on_appointment_created(self, appointment_id: str, seeker_user_id: str,
                            provider_user_id: str, amount: str, **kwargs):
    """
    Hold escrow when a booking is created (PENDING).
    Called by the RabbitMQ consumer after APPOINTMENT_CREATED event.
    """
    from decimal import Decimal
    from .services import hold_escrow
    idempotency_key = f"escrow_hold:{appointment_id}"
    try:
        hold_escrow(
            appointment_id   = appointment_id,
            seeker_user_id   = seeker_user_id,
            provider_user_id = provider_user_id,
            amount           = Decimal(str(amount)),
            idempotency_key  = idempotency_key,
        )
        logger.info("Escrow held", extra={"appointment_id": appointment_id})
    except Exception as exc:
        logger.error("Escrow hold failed", extra={"appointment_id": appointment_id, "error": str(exc)})
        raise self.retry(exc=exc)


@shared_task(
    name="payments.tasks.on_appointment_confirmed",
    bind=True, max_retries=3, default_retry_delay=30,
    queue="payments",
)
def on_appointment_confirmed(self, appointment_id: str, **kwargs):
    """Release escrow after seeker confirms completion."""
    from .services import release_escrow
    idempotency_key = f"escrow_release:{appointment_id}"
    try:
        release_escrow(appointment_id=appointment_id, idempotency_key=idempotency_key)
        logger.info("Escrow released (confirmed)", extra={"appointment_id": appointment_id})
    except Exception as exc:
        logger.error("Escrow release failed", extra={"appointment_id": appointment_id, "error": str(exc)})
        raise self.retry(exc=exc)


@shared_task(
    name="payments.tasks.on_appointment_auto_released",
    bind=True, max_retries=3, default_retry_delay=30,
    queue="payments",
)
def on_appointment_auto_released(self, appointment_id: str, **kwargs):
    """Release escrow after 48h auto-release."""
    from .services import release_escrow
    idempotency_key = f"escrow_auto_release:{appointment_id}"
    try:
        release_escrow(appointment_id=appointment_id, idempotency_key=idempotency_key)
        logger.info("Escrow auto-released", extra={"appointment_id": appointment_id})
    except Exception as exc:
        logger.error("Escrow auto-release failed", extra={"appointment_id": appointment_id, "error": str(exc)})
        raise self.retry(exc=exc)


@shared_task(
    name="payments.tasks.on_appointment_rejected_or_expired",
    bind=True, max_retries=3, default_retry_delay=30,
    queue="payments",
)
def on_appointment_rejected_or_expired(self, appointment_id: str, **kwargs):
    """Full refund on rejection or expiry."""
    from .services import refund_escrow
    idempotency_key = f"escrow_refund_full:{appointment_id}"
    try:
        refund_escrow(appointment_id=appointment_id, idempotency_key=idempotency_key)
        logger.info("Escrow refunded (rejected/expired)", extra={"appointment_id": appointment_id})
    except Exception as exc:
        logger.error("Escrow refund failed", extra={"appointment_id": appointment_id, "error": str(exc)})
        raise self.retry(exc=exc)


@shared_task(
    name="payments.tasks.on_appointment_cancelled",
    bind=True, max_retries=3, default_retry_delay=30,
    queue="payments",
)
def on_appointment_cancelled(self, appointment_id: str, cancelled_by: str = "",
                              quoted_price: str = "0", **kwargs):
    """
    Apply cancellation policy on CANCELLED event.
    The cancellation timing determines the refund split.
    """
    

    try:
        apt = Appointment.objects.get(id=appointment_id)
    except Appointment.DoesNotExist:
        logger.error("Appointment not found for cancellation refund", extra={"appointment_id": appointment_id})
        return

    # Determine refund amount based on SRS §7.5 cancellation policy
    from django.utils import timezone
    import datetime
    scheduled_dt = datetime.datetime.combine(apt.scheduled_date, apt.scheduled_time)
    if timezone.is_naive(scheduled_dt):
        scheduled_dt = timezone.make_aware(scheduled_dt)
    hours_until = (scheduled_dt - timezone.now()).total_seconds() / 3600
    amount = Decimal(str(quoted_price)) or apt.quoted_price

    if apt.accepted_at is None:
        # Before provider accepted — full refund
        partial = None
    elif hours_until > 48:
        # >48h before appointment — full refund
        partial = None
    elif 24 <= hours_until <= 48:
        # 24–48h — 50% refund
        partial = (amount * Decimal("0.5")).quantize(Decimal("0.01"))
    else:
        # <24h or provider cancelled — no refund to seeker
        if cancelled_by == "provider":
            partial = None   # provider cancels → full refund to seeker
        else:
            partial = Decimal("0.00")  # seeker cancels late → no refund

    idempotency_key = f"escrow_cancel:{appointment_id}"
    try:
        if partial == Decimal("0.00"):
            # Release full amount to provider (no refund)
            from .services import release_escrow
            release_escrow(appointment_id=appointment_id,
                           idempotency_key=f"escrow_cancel_release:{appointment_id}")
        else:
            refund_escrow(appointment_id=appointment_id,
                          idempotency_key=idempotency_key,
                          partial_amount=partial)
        logger.info("Cancellation escrow handled", extra={"appointment_id": appointment_id})
    except Exception as exc:
        logger.error("Cancellation escrow failed", extra={"appointment_id": appointment_id, "error": str(exc)})
        raise self.retry(exc=exc)
