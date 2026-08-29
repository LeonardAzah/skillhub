"""
Appointment / booking lifecycle event handlers.

Covers: creation, accept/reject, start, completion, confirmation,
cancellation, expiry, auto-release, and reminders.
"""
from notifications.models import Notification
from notifications._helper import _create_notification, _enqueue_push, _enqueue_email, _enqueue_escrow_task
from payments.tasks import on_appointment_created


def handle_appointment_created(payload: dict, event_id: str = "") -> None:
    """New booking request → Push + Email to provider."""
    provider_id = payload.get("provider_id")
    notif_type  = Notification.NotificationType.BOOKING_REQUEST
    title       = "New booking request"
    body        = (
        f"You have a new booking request for {payload.get('category', 'a service')} "
        f"on {payload.get('scheduled_date', '')}."
    )
    data = {
        "type":           "booking_request",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      f"/appointments/{payload.get('appointment_id')}",
    }

    # escrow hold
    _enqueue_escrow_task(
        "payments.tasks.on_appointment_created",
        {
            "appointment_id": payload.get("appointment_id"),
            "seeker_user_id": payload.get("seeker_id"),
            "provider_user_id": payload.get("provider_id"),
            "amount": str(payload.get("quoted_price", "0")),
        },
    )

    # Notification
    _create_notification(provider_id, notif_type, title, body, data, event_id)
    _enqueue_push(provider_id, title, body, data)
    _enqueue_email(
        provider_id, "email/booking_request.html",
        {**payload, "title": title},
        subject=title,
    )

    on_appointment_created.apply_async(
        kwargs={
            "appointment_id":   payload["appointment_id"],
            "seeker_user_id":   payload["seeker_id"],
            "provider_user_id": payload["provider_id"],
            "amount":           payload["quoted_price"],
        },
        queue="payments",
    )


def handle_appointment_accepted(payload: dict, event_id: str = "") -> None:
    """Booking accepted → Push + Email to seeker."""
    seeker_id  = payload.get("seeker_id")
    notif_type = Notification.NotificationType.BOOKING_ACCEPTED
    title      = "Booking accepted ✓"
    body       = "Your booking has been accepted. The provider will arrive at the scheduled time."
    data       = {
        "type":           "booking_accepted",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      f"/appointments/{payload.get('appointment_id')}",
    }

    _create_notification(seeker_id, notif_type, title, body, data, event_id)
    _enqueue_push(seeker_id, title, body, data)
    _enqueue_email(seeker_id, "email/booking_accepted.html", {**payload, "title": title}, subject=title)

    from payments.tasks import on_appointment_accepted
    on_appointment_accepted.apply_async(
        kwargs={
            "appointment_id":   payload["appointment_id"],
            "seeker_user_id":   payload["seeker_id"],
            "provider_user_id": payload["provider_id"],
            "amount":           payload["quoted_price"],
        },
        queue="payments",
    )


def handle_appointment_rejected(payload: dict, event_id: str = "") -> None:
    """Booking rejected → Push + Email to seeker (escrow refunded)."""
    seeker_id  = payload.get("seeker_id")
    notif_type = Notification.NotificationType.BOOKING_REJECTED
    title      = "Booking declined"
    body       = "Your booking was declined by the provider. Your payment has been refunded."
    data       = {
        "type":           "booking_rejected",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      "/appointments",
    }

    _enqueue_escrow_task(
        "payments.tasks.on_appointment_rejected_or_expired",
        {"appointment_id": payload.get("appointment_id")},
    )

    _create_notification(seeker_id, notif_type, title, body, data, event_id)
    _enqueue_push(seeker_id, title, body, data)
    _enqueue_email(seeker_id, "email/booking_rejected.html", {**payload, "title": title}, subject=title)

    from payments.tasks import on_appointment_rejected_or_expired
    on_appointment_rejected_or_expired.apply_async(
        kwargs={
            "appointment_id":   payload["appointment_id"],
            "seeker_user_id":   payload["seeker_id"],
            "provider_user_id": payload["provider_id"],
            "amount":           payload["quoted_price"],
        },
        queue="payments",
    )


def handle_appointment_started(payload: dict, event_id: str = "") -> None:
    """Job started → Push to seeker."""
    seeker_id  = payload.get("seeker_id")
    notif_type = Notification.NotificationType.JOB_STARTED
    title      = "Job started"
    body       = "The provider has marked your job as started."
    data       = {
        "type":           "job_started",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      f"/appointments/{payload.get('appointment_id')}",
    }

    _create_notification(seeker_id, notif_type, title, body, data, event_id)
    _enqueue_push(seeker_id, title, body, data)


def handle_appointment_completed(payload: dict, event_id: str = "") -> None:
    """Job marked complete → Push + Email to seeker to confirm or dispute."""
    seeker_id  = payload.get("seeker_id")
    notif_type = Notification.NotificationType.JOB_COMPLETED
    title      = "Job completed — please confirm"
    body       = "The provider has marked the job as complete. Please confirm or raise a dispute within 48 hours."
    data       = {
        "type":           "job_completed",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      f"/appointments/{payload.get('appointment_id')}/confirm",
    }

    _create_notification(seeker_id, notif_type, title, body, data, event_id)
    _enqueue_push(seeker_id, title, body, data)
    _enqueue_email(seeker_id, "email/job_completed.html", {**payload, "title": title}, subject=title)


def handle_appointment_confirmed(payload: dict, event_id: str = "") -> None:
    """Seeker confirmed → Push + Email to provider (payment released)."""
    provider_id = payload.get("provider_id")
    notif_type  = Notification.NotificationType.JOB_CONFIRMED
    title       = "Job confirmed — payment released ✓"
    body        = "The client has confirmed the job. Payment has been released to your wallet."
    data        = {
        "type":           "job_confirmed",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      "/wallet",
    }

    -_enqueue_escrow_task(
        "payments.tasks.on_appointment_confirmed",
        {"appointment_id": payload.get("appointment_id")},
    )

    _create_notification(provider_id, notif_type, title, body, data, event_id)
    _enqueue_push(provider_id, title, body, data)
    _enqueue_email(provider_id, "email/job_confirmed.html", {**payload, "title": title}, subject=title)


def handle_appointment_cancelled(payload: dict, event_id: str = "") -> None:
    """Cancellation → Push + Email to both parties."""
    seeker_id   = payload.get("seeker_id")
    provider_id = payload.get("provider_id")
    notif_type  = Notification.NotificationType.BOOKING_CANCELLED
    title       = "Booking cancelled"
    body        = f"Appointment cancelled. Reason: {payload.get('reason', 'Not specified')}."
    data        = {
        "type":           "booking_cancelled",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      "/appointments",
    }


    _enqueue_escrow_task(
         "payments.tasks.on_appointment_cancelled",
        {
            "appointment_id": payload.get("appointment_id"),
            "cancelled_by":   payload.get("cancelled_by", ""),
            "quoted_price":   str(payload.get("quoted_price", "0")),
        },
    )

    for uid in filter(None, [seeker_id, provider_id]):
        _create_notification(uid, notif_type, title, body, data, event_id + f"_{uid}")
        _enqueue_push(uid, title, body, data)
        _enqueue_email(uid, "email/booking_cancelled.html", {**payload, "title": title}, subject=title)

    from payments.tasks import on_appointment_cancelled
    on_appointment_cancelled.apply_async(
        kwargs={
            "appointment_id":   payload["appointment_id"],
            "seeker_user_id":   payload["seeker_id"],
            "provider_user_id": payload["provider_id"],
            "amount":           payload["quoted_price"],
        },
        queue="payments",
    )


def handle_appointment_expired(payload: dict, event_id: str = "") -> None:
    """EXPIRED (24h no provider response) → Push + Email to seeker."""
    seeker_id  = payload.get("seeker_id")
    notif_type = Notification.NotificationType.BOOKING_EXPIRED
    title      = "Booking expired — refund issued"
    body       = "The provider did not respond within 24 hours. Your payment has been refunded."
    data       = {"type": "booking_expired", "appointment_id": payload.get("appointment_id"), "deep_link": "/appointments"}

    _enqueue_escrow_task(
        "payments.tasks.on_appointment_rejected_or_expired",
        {"appointment_id": payload.get("appointment_id")},
    )

    _create_notification(seeker_id, notif_type, title, body, data, event_id)
    _enqueue_push(seeker_id, title, body, data)
    _enqueue_email(seeker_id, "email/booking_expired.html", {**payload, "title": title}, subject=title)

    from payments.tasks import on_appointment_rejected_or_expired
    on_appointment_rejected_or_expired.apply_async(
        kwargs={
            "appointment_id":   payload["appointment_id"],
            "seeker_user_id":   payload["seeker_id"],
            "provider_user_id": payload["provider_id"],
            "amount":           payload["quoted_price"],
        },
        queue="payments",
    )


def handle_appointment_auto_released(payload: dict, event_id: str = "") -> None:
    """AUTO_RELEASED (48h no seeker response) → Push + Email to both."""
    seeker_id   = payload.get("seeker_id")
    provider_id = payload.get("provider_id")
    notif_type  = Notification.NotificationType.ESCROW_AUTO_RELEASED

    seeker_title    = "Payment auto-released to provider"
    seeker_body     = "You did not confirm or dispute within 48 hours. Payment has been released to the provider."
    provider_title  = "Payment released to your wallet ✓"
    provider_body   = "As no dispute was raised within 48 hours, your payment has been released."
    data = {"type": "escrow_auto_released", "appointment_id": payload.get("appointment_id"), "deep_link": "/wallet"}

    _enqueue_escrow_task(
        "payments.tasks.on_appointment_auto_released",
        {"appointment_id": payload.get("appointment_id")},
    )

    if seeker_id:
        _create_notification(seeker_id, notif_type, seeker_title, seeker_body, data, event_id + "_seeker")
        _enqueue_push(seeker_id, seeker_title, seeker_body, data)
        _enqueue_email(seeker_id, "email/auto_released.html", {**payload, "title": seeker_title}, subject=seeker_title)
    if provider_id:
        _create_notification(provider_id, notif_type, provider_title, provider_body, data, event_id + "_provider")
        _enqueue_push(provider_id, provider_title, provider_body, data)
        _enqueue_email(provider_id, "email/auto_released.html", {**payload, "title": provider_title}, subject=provider_title)

    from payments.tasks import on_appointment_auto_released
    on_appointment_auto_released.apply_async(
        kwargs={
            "appointment_id":   payload["appointment_id"],
            "seeker_user_id":   payload["seeker_id"],
            "provider_user_id": payload["provider_id"],
            "amount":           payload["quoted_price"],
        },
        queue="payments",
    )


def handle_appointment_reminder(payload: dict, event_id: str = "", hours: int = 24) -> None:
    """T-24h and T-2h reminders → Push to both parties."""
    seeker_id   = payload.get("seeker_id")
    provider_id = payload.get("provider_id")
    notif_type  = (
        Notification.NotificationType.REMINDER_24H if hours == 24
        else Notification.NotificationType.REMINDER_2H
    )
    title = f"Appointment reminder — {hours} hour{'s' if hours > 1 else ''} to go"
    body  = (
        f"Your appointment is in {hours} hour{'s' if hours > 1 else ''} "
        f"on {payload.get('scheduled_date', '')} at {payload.get('scheduled_time', '')}."
    )
    data = {
        "type":           "reminder",
        "appointment_id": payload.get("appointment_id"),
        "hours":          hours,
        "deep_link":      f"/appointments/{payload.get('appointment_id')}",
    }

    for uid in filter(None, [seeker_id, provider_id]):
        _create_notification(uid, notif_type, title, body, data, event_id + f"_{uid}")
        _enqueue_push(uid, title, body, data)
