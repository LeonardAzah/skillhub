"""
Tasks
expire_pending_appointments - PENDING -> EXPIRED after 24h
auto_release_escrow - COMPLETED -> AUTO_RELEASED after 48h
send_appointment_reminders - push reminders at T-24h and T-2h
"""

import logging

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import Appointment

from notifications.events import EventType
from notifications.publisher import publish_event
from accounts.models import ProviderProfile


logger = logging.getLogger(__name__)


@shared_task(
        name="appointments.tasks.expire_pending_appointments",
        bind=True,
        max_retries=3,
        default_retry_delay=60,
)
def expire_pending_appointments(self):
    """
    Any pending appointment not accepted/rejected with 24 hours is moved to 
    expired and a refund is triggered for the escrow funds.
    Runs every 10 minutes (see skillhub/celery.py beat schedule)
    """

    cutoff = timezone.now() - timedelta(hours=24)
    expiring_appointments = Appointment.objects.filter(
        status=Appointment.Status.PENDING,
        created_at__lte=cutoff
    ).select_related("provider__user", "customer__user", "category")

    expired_count = 0
    for appointment in expiring_appointments:
        try:
            appointment.transition_to(Appointment.Status.EXPIRED)
            publish_event(EventType.APPOINTMENT_EXPIRED, {
                "appointment_id": str(appointment.id),
                "provider_id": str(appointment.provider.id),
                "seeker_id": str(appointment.customer.id),
                "category": appointment.category.title,
                "scheduled_date": str(appointment.scheduled_at),
                "quoted_price": str(appointment.quoted_price),
                "status": appointment.status,
            })
            expired_count += 1

        except Exception as exc:
            logger.error(
                "Failed to expire appointment",
                extra={"appointment_id": str(appointment.id), "error":str(exc)},
            )
    logger.info("Expired pending appointments", extra={"count": expired_count})
    return {"status":"ok", "expired": expired_count}


@shared_task(
        name="appointments.tasks.auto_release_escrow",
        bind=True,
        max_retries=3,
        default_retry_delay=60,
)
def auto_release_escrow(self):
    """
    COMPLETED appointments where the seeker has not responded
    within 48 hours are moved to auto released.
    Escrow release is handled by the payment module listening to this event.
    Runs every 5 minutes
    """

    cutoff = timezone.now() - timedelta(hours=48)
    releasing = Appointment.objects.filter(
        status=Appointment.Status.COMPLETED,
        completed_at__lte = cutoff,
    ).select_related("provider__user", "customer__user", "category")

    release_count = 0
    for appointment in releasing:
        #Safety check: skip if a dispute was raised concurrently
        if appointment.status == Appointment.Status.DISPUTED:
            continue
        try:
            appointment.transition_to(Appointment.Status.AUTO_RELEASED)

            # Increment provider's total_jobs
            ProviderProfile.objects.filter(pk=appointment.provider.pk).update(
                total_jobs=appointment.provider.total_jobs +1
            )

            publish_event(EventType.APPOINTMENT_AUTO_RELEASED, {
                "appointment_id": str(appointment.id),
                "provider_id": str(appointment.provider.id),
                "seeker_id": str(appointment.customer.id),
                "category": appointment.category.title,
                "scheduled_date": str(appointment.scheduled_at),
                "quoted_price": str(appointment.quoted_price),
                "escrow_transaction_id": str(appointment.escrow_transaction_id) if appointment.escrow_transaction_id else None,
                "status": appointment.status,
            })
            release_count += 1
        except Exception as exc:
            logger.error(
                "Failed to auto-release appointment",
                extra={"appointment_id": str(appointment.id), "error": str(exc)},
            )
    logger.info("Auto-released escrow for appointments", extra={"count": release_count})
    return {"status": "ok", "released": release_count}


@shared_task(
    name="appointments.tasks.send_appointment_reminders",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_appointment_reminder(self):
    """
    Send push reminders at T-24h and T-2h for ACCEPTED appointments.
    Runs every 30 minutes.
    """

    now = timezone.now()
    sent_24h = 0
    sent_2h = 0

    accepted_appointments = Appointment.objects.filter(
        status=Appointment.Status.ACCEPTED,
    ).select_related("provider__user", "customer__user", "category")

    for appointment in accepted_appointments:
        time_until = timezone(appointment.scheduled_at) - now
        hours_until = time_until.total_seconds() / 3600

        base = {
            "appointment_id": str(appointment.id),
            "provider_id": str(appointment.provider.id),
            "seeker_id": str(appointment.customer.id),
            "scheduled_date": str(appointment.scheduled_at),
            "scheduled_time": str(appointment.scheduled_at),
        }

        if 23<= hours_until <= 25 and not appointment.reminder_sent_24h:
            publish_event(EventType.APPOINTMENT_REMINDER_24H, base)
            appointment.reminder_sent_24h = True
            appointment.save(update_fields=["reminder_sent_24h"])
            sent_24h += 1
        elif 1.5 <= hours_until <=2.5 and not appointment.reminder_sent_2h:
            publish_event(EventType.APPOINTMENT_REMINDER_2H, base)
            appointment.reminder_sent_2h = True
            appointment.save(update_fields=["reminder_sent_2h"])
            sent_2h += 1
    logger.info(
        "Appointment reminders sent",
        extra={"24h": sent_24h, "2h": sent_2h},
    )
    return {"status": "ok", "sent_24h": sent_24h, "sent_2h": sent_2h}

