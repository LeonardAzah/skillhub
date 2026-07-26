"""
Event handlers — one function per event type.

Each handler receives the raw event payload dict and is responsible for:
  1. Creating an in-app Notification record
  2. Dispatching push notification via FCM (Celery task)
  3. Dispatching email via SES (Celery task)

Handlers are registered in the HANDLER_REGISTRY at the bottom of this file.
The RabbitMQ consumer calls dispatch(event_type, payload) which resolves
the right handler(s) and calls them.

SRS §10.1 — full notification type catalogue
SRS §10.2 — FCM push architecture
SRS §10.3 — SES email architecture
"""
import logging
from typing import Callable

from .events import EventType
from .models import Notification
from accounts.models import User
# from payments.tasks import on_appointment_created





logger = logging.getLogger(__name__)


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _create_notification(
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    data: dict,
    event_id: str = "",
    event_type: str = "",
) -> Notification | None:
    """Persist in-app notification. Returns None if user not found."""
    from accounts.models import User
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("Notification skipped - user not found", extra={"user_id": user_id})
        return None

    # Idempotency: skip duplicate events
    if event_id and Notification.objects.filter(event_id=event_id, user=user).exists():
        logger.debug("Duplicate event skipped", extra={"event_id": event_id})
        return None

    return Notification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        body=body,
        data=data,
        event_id=event_id,
        event_type=event_type,
    )


def _enqueue_push(user_id: str, title: str, body: str, data: dict) -> None:
    """Enqueue FCM push notification Celery task."""
    from .tasks import send_push_notification_task

    try:
        send_push_notification_task.apply_async(
            kwargs={"user_id": user_id, "title": title, "body": body, "data": data},
            queue="notifications",
        )
    except Exception as exc:
        logger.error("Failed to enqueue push notification", extra={"user_id": user_id, "error": str(exc)})


def _enqueue_email(user_id: str, template: str, context: dict, subject: str = "") -> None:
    """Enqueue SES email Celery task."""
    try:
        from .tasks import send_email_notification_task
        send_email_notification_task.apply_async(
            kwargs={"user_id": user_id, "template": template, "context": context, "subject": subject},
            queue="notifications",
        )
    except Exception as exc:
        logger.error("Failed to enqueue email notification", extra={"user_id": user_id, "error": str(exc)})


def _check_preference(user_id: str, notif_type: str, channel: str) -> bool:
    """Return True if user has the given channel enabled for this notification type."""
    from .models import NotificationPreference
    pref = NotificationPreference.objects.filter(
        user_id=user_id, notification_type=notif_type
    ).first()
    if pref is None:
        return True  # default: all channels enabled
    return getattr(pref, f"{channel}_enabled", True)


# ─── Account handlers ─────────────────────────────────────────────────────────

def handle_verification_requested(payload: dict, event_id: str = "") -> None:
    """
    Send email verification link.
    The accounts module includes the fully-formed verify_url in the payload
    so this handler never needs to know about URL routing or settings.
    """
    user_id    = payload.get("user_id")
    username   = payload.get("username", "")
    verify_url = payload.get("verify_url", "")
    expiry     = payload.get("expiry_hours", 24)
    token      = payload.get("token", "")

    # Email only — no in-app notification for verification request
    _enqueue_email(
        user_id,
        "email/verify_email.html",
        {
            "user_id":      user_id,
            "username":     username,
            "verify_url":   verify_url,
            "expiry_hours": expiry,
            "token":        token,
        },
        subject="Verify your SkillHub email",
    )


def handle_password_reset_requested(payload: dict, event_id: str = "") -> None:
    """
    Send password reset email.
    Full reset_url is included in the payload by the accounts module.
    """
    user_id    = payload.get("user_id")
    username   = payload.get("username", "")
    reset_url  = payload.get("reset_url", "")
    expiry     = payload.get("expiry_hours", 1)
    ip_address = payload.get("ip_address", "Unknown")

    # Email only — no in-app notification for password reset request
    _enqueue_email(
        user_id,
        "email/password_reset.html",
        {
            "user_id":      user_id,
            "username":     username,
            "reset_url":    reset_url,
            "expiry_hours": expiry,
            "ip_address":   ip_address,
        },
        subject="Reset your BoloConnect password",
    )


def handle_user_registered(payload: dict, event_id: str = "") -> None:
    
    user_id  = payload.get("user_id")
    email    = payload.get("email", "")
    username = payload.get("username", "")

    notif_type = Notification.NotificationType.ACCOUNT_VERIFIED
    title      = "Welcome to SkillHub!"
    body       = f"Hi {username}, your account has been created. Please verify your email to get started."
    data       = {"type": "account_verified", "deep_link": "/onboarding"}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    if _check_preference(user_id, notif_type, "push"):
        _enqueue_push(user_id, title, body, data)
    if _check_preference(user_id, notif_type, "email"):
        _enqueue_email(user_id, "email/welcome.html", {"user_id": user_id, "username": username}, subject=title)


def handle_kyc_submitted(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — KYC submitted → Push to user, Email to admin."""
    user_id = payload.get("user_id")
    notif_type = Notification.NotificationType.KYC_SUBMITTED
    title      = "KYC documents received"
    body       = "Your identity documents have been submitted. We'll notify you within 1–2 business days."
    data       = {"type": "kyc_submitted", "deep_link": "/profile/verify/status"}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    _enqueue_push(user_id, title, body, data)
    _enqueue_email(user_id, "email/kyc_submitted.html", {"user_id": user_id}, subject=title)

    # Admin alert
    _notify_admins(
        title="New KYC pending review",
        body=f"User {payload.get('email')} has submitted KYC documents.",
        data={"type": "admin_kyc_pending", "user_id": user_id, "deep_link": f"/admin/kyc/{user_id}"},
        event_id=event_id + "_admin",
    )


def handle_kyc_approved(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — KYC approved → Email + Push."""
    user_id    = payload.get("user_id")
    notif_type = Notification.NotificationType.KYC_APPROVED
    title      = "Identity verified ✓"
    body       = "Your identity has been verified. You can now accept bookings."
    data       = {"type": "kyc_approved", "deep_link": "/profile"}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    _enqueue_push(user_id, title, body, data)
    _enqueue_email(user_id, "email/kyc_approved.html", {"user_id": user_id}, subject=title)


def handle_kyc_rejected(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — KYC rejected → Email + Push with reason."""
    user_id    = payload.get("user_id")
    reason     = payload.get("reason", "")
    notif_type = Notification.NotificationType.KYC_REJECTED
    title      = "KYC verification unsuccessful"
    body       = f"We could not verify your identity. Reason: {reason}"
    data       = {"type": "kyc_rejected", "deep_link": "/profile/verify", "reason": reason}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    _enqueue_push(user_id, title, body, data)
    _enqueue_email(
        user_id, "email/kyc_rejected.html",
        {"user_id": user_id, "rejection_reason": reason},
        subject=title,
    )


def handle_account_locked(payload: dict, event_id: str = "") -> None:
    """SRS §4.5 — Account locked → Email alert."""
    user_id         = payload.get("user_id")
    lockout_minutes = payload.get("lockout_minutes", 30)
    _enqueue_email(
        user_id, "email/account_lockout.html",
        {"user_id": user_id, "lockout_minutes": lockout_minutes},
        subject="Security alert: your account has been temporarily locked",
    )


def handle_password_changed(payload: dict, event_id: str = "") -> None:
    """Password changed → Email security alert."""
    user_id = payload.get("user_id")
    _enqueue_email(
        user_id, "email/password_changed.html",
        {"user_id": user_id},
        subject="Your BoloConnect password has been changed",
    )


# ─── Appointment handlers ─────────────────────────────────────────────────────

# def handle_appointment_created(payload: dict, event_id: str = "") -> None:
#     """SRS §10.1 — New booking request → Push + Email to provider."""
#     provider_id = payload.get("provider_id")
#     notif_type  = Notification.NotificationType.BOOKING_REQUEST
#     title       = "New booking request"
#     body        = (
#         f"You have a new booking request for {payload.get('category', 'a service')} "
#         f"on {payload.get('scheduled_date', '')}."
#     )
#     data = {
#         "type":           "booking_request",
#         "appointment_id": payload.get("appointment_id"),
#         "deep_link":      f"/appointments/{payload.get('appointment_id')}",
#     }

#     _create_notification(provider_id, notif_type, title, body, data, event_id)
#     _enqueue_push(provider_id, title, body, data)
#     _enqueue_email(
#         provider_id, "email/booking_request.html",
#         {**payload, "title": title},
#         subject=title,
#     )

#     on_appointment_created.apply_async(
#     kwargs={
#         "appointment_id":   payload["appointment_id"],
#         "seeker_user_id":   payload["seeker_id"],
#         "provider_user_id": payload["provider_id"],
#         "amount":           payload["quoted_price"],
#     },
#     queue="payments",
# )


# def handle_appointment_accepted(payload: dict, event_id: str = "") -> None:
#     """SRS §10.1 — Booking accepted → Push + Email to seeker."""
#     seeker_id  = payload.get("seeker_id")
#     notif_type = Notification.NotificationType.BOOKING_ACCEPTED
#     title      = "Booking accepted ✓"
#     body       = "Your booking has been accepted. The provider will arrive at the scheduled time."
#     data       = {
#         "type":           "booking_accepted",
#         "appointment_id": payload.get("appointment_id"),
#         "deep_link":      f"/appointments/{payload.get('appointment_id')}",
#     }

#     _create_notification(seeker_id, notif_type, title, body, data, event_id)
#     _enqueue_push(seeker_id, title, body, data)
#     _enqueue_email(seeker_id, "email/booking_accepted.html", {**payload, "title": title}, subject=title)
#     from ayments.tasks import on_appointment_accepted
#     on_appointment_accepted.apply_async(
#     kwargs={
#         "appointment_id":   payload["appointment_id"],
#         "seeker_user_id":   payload["seeker_id"],
#         "provider_user_id": payload["provider_id"],
#         "amount":           payload["quoted_price"],
#     },
#     queue="payments",
# )


# def handle_appointment_rejected(payload: dict, event_id: str = "") -> None:
#     """SRS §10.1 — Booking rejected → Push + Email to seeker (escrow refunded)."""
#     seeker_id  = payload.get("seeker_id")
#     notif_type = Notification.NotificationType.BOOKING_REJECTED
#     title      = "Booking declined"
#     body       = "Your booking was declined by the provider. Your payment has been refunded."
#     data       = {
#         "type":           "booking_rejected",
#         "appointment_id": payload.get("appointment_id"),
#         "deep_link":      "/appointments",
#     }

#     _create_notification(seeker_id, notif_type, title, body, data, event_id)
#     _enqueue_push(seeker_id, title, body, data)
#     _enqueue_email(seeker_id, "email/booking_rejected.html", {**payload, "title": title}, subject=title)

#     from payments.tasks import on_appointment_rejected_or_expired
#     on_appointment_rejected_or_expired.apply_async(
#     kwargs={
#         "appointment_id":   payload["appointment_id"],
#         "seeker_user_id":   payload["seeker_id"],
#         "provider_user_id": payload["provider_id"],
#         "amount":           payload["quoted_price"],
#     },
#     queue="payments",
# )


def handle_appointment_started(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — Job started → Push to seeker."""
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
    """SRS §10.1 — Job marked complete → Push + Email to seeker to confirm or dispute."""
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
    """SRS §10.1 — Seeker confirmed → Push + Email to provider (payment released)."""
    provider_id = payload.get("provider_id")
    notif_type  = Notification.NotificationType.JOB_CONFIRMED
    title       = "Job confirmed — payment released ✓"
    body        = "The client has confirmed the job. Payment has been released to your wallet."
    data        = {
        "type":           "job_confirmed",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      "/wallet",
    }

    _create_notification(provider_id, notif_type, title, body, data, event_id)
    _enqueue_push(provider_id, title, body, data)
    _enqueue_email(provider_id, "email/job_confirmed.html", {**payload, "title": title}, subject=title)


# def handle_appointment_cancelled(payload: dict, event_id: str = "") -> None:
#     """SRS §10.1 — Cancellation → Push + Email to both parties."""
#     seeker_id   = payload.get("seeker_id")
#     provider_id = payload.get("provider_id")
#     notif_type  = Notification.NotificationType.BOOKING_CANCELLED
#     title       = "Booking cancelled"
#     body        = f"Appointment cancelled. Reason: {payload.get('reason', 'Not specified')}."
#     data        = {
#         "type":           "booking_cancelled",
#         "appointment_id": payload.get("appointment_id"),
#         "deep_link":      "/appointments",
#     }

#     for uid in filter(None, [seeker_id, provider_id]):
#         _create_notification(uid, notif_type, title, body, data, event_id + f"_{uid}")
#         _enqueue_push(uid, title, body, data)
#         _enqueue_email(uid, "email/booking_cancelled.html", {**payload, "title": title}, subject=title)
    
#     from payments.tasks import on_appointment_cancelled
#     on_appointment_cancelled.apply_async(
#     kwargs={
#         "appointment_id":   payload["appointment_id"],
#         "seeker_user_id":   payload["seeker_id"],
#         "provider_user_id": payload["provider_id"],
#         "amount":           payload["quoted_price"],
#     },
#     queue="payments",
# )
    
    


# def handle_appointment_expired(payload: dict, event_id: str = "") -> None:
#     """SRS §7.4 — EXPIRED (24h no provider response) → Push + Email to seeker."""
#     seeker_id  = payload.get("seeker_id")
#     notif_type = Notification.NotificationType.BOOKING_EXPIRED
#     title      = "Booking expired — refund issued"
#     body       = "The provider did not respond within 24 hours. Your payment has been refunded."
#     data       = {"type": "booking_expired", "appointment_id": payload.get("appointment_id"), "deep_link": "/appointments"}

#     _create_notification(seeker_id, notif_type, title, body, data, event_id)
#     _enqueue_push(seeker_id, title, body, data)
#     _enqueue_email(seeker_id, "email/booking_expired.html", {**payload, "title": title}, subject=title)

#     from payments.tasks import on_appointment_rejected_or_expired
#     on_appointment_rejected_or_expired.apply_async(
#     kwargs={
#         "appointment_id":   payload["appointment_id"],
#         "seeker_user_id":   payload["seeker_id"],
#         "provider_user_id": payload["provider_id"],
#         "amount":           payload["quoted_price"],
#     },
#     queue="payments",
# )


def handle_appointment_auto_released(payload: dict, event_id: str = "") -> None:
    """SRS §7.4 — AUTO_RELEASED (48h no seeker response) → Push + Email to both."""
    seeker_id   = payload.get("seeker_id")
    provider_id = payload.get("provider_id")
    notif_type  = Notification.NotificationType.ESCROW_AUTO_RELEASED

    seeker_title    = "Payment auto-released to provider"
    seeker_body     = "You did not confirm or dispute within 48 hours. Payment has been released to the provider."
    provider_title  = "Payment released to your wallet ✓"
    provider_body   = "As no dispute was raised within 48 hours, your payment has been released."
    data = {"type": "escrow_auto_released", "appointment_id": payload.get("appointment_id"), "deep_link": "/wallet"}

    if seeker_id:
        _create_notification(seeker_id, notif_type, seeker_title, seeker_body, data, event_id + "_seeker")
        _enqueue_push(seeker_id, seeker_title, seeker_body, data)
        _enqueue_email(seeker_id, "email/auto_released.html", {**payload, "title": seeker_title}, subject=seeker_title)
    if provider_id:
        _create_notification(provider_id, notif_type, provider_title, provider_body, data, event_id + "_provider")
        _enqueue_push(provider_id, provider_title, provider_body, data)
        _enqueue_email(provider_id, "email/auto_released.html", {**payload, "title": provider_title}, subject=provider_title)

#     from payments.tasks import on_appointment_auto_released
#     on_appointment_auto_released.apply_async(
#     kwargs={
#         "appointment_id":   payload["appointment_id"],
#         "seeker_user_id":   payload["seeker_id"],
#         "provider_user_id": payload["provider_id"],
#         "amount":           payload["quoted_price"],
#     },
#     queue="payments",
# )


def handle_appointment_reminder(payload: dict, event_id: str = "", hours: int = 24) -> None:
    """SRS §10.1 — T-24h and T-2h reminders → Push to both parties."""
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


# ─── Payment handlers ─────────────────────────────────────────────────────────

def handle_wallet_credited(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — Wallet top-up → Email + Push."""
    user_id    = payload.get("user_id")
    amount     = payload.get("amount", 0)
    currency   = payload.get("currency", "XAF")
    notif_type = Notification.NotificationType.WALLET_CREDITED
    title      = f"Wallet credited {amount} {currency}"
    body       = f"Your wallet has been topped up with {amount} {currency}."
    data       = {"type": "wallet_credited", "amount": amount, "currency": currency, "deep_link": "/wallet"}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    _enqueue_push(user_id, title, body, data)
    _enqueue_email(user_id, "email/wallet_credited.html", {**payload, "title": title}, subject=title)


def handle_withdrawal_initiated(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — Withdrawal initiated → Email + Push."""
    user_id    = payload.get("user_id")
    amount     = payload.get("amount", 0)
    currency   = payload.get("currency", "XAF")
    notif_type = Notification.NotificationType.WITHDRAWAL_INITIATED
    title      = f"Withdrawal of {amount} {currency} initiated"
    body       = "Your withdrawal request is being processed. Funds will arrive within 1–3 business days."
    data       = {"type": "withdrawal_initiated", "amount": amount, "deep_link": "/wallet"}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    _enqueue_push(user_id, title, body, data)
    _enqueue_email(user_id, "email/withdrawal_initiated.html", {**payload, "title": title}, subject=title)


def handle_withdrawal_completed(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — Withdrawal completed → Email + Push."""
    user_id    = payload.get("user_id")
    amount     = payload.get("amount", 0)
    currency   = payload.get("currency", "XAF")
    notif_type = Notification.NotificationType.WITHDRAWAL_COMPLETED
    title      = f"Withdrawal of {amount} {currency} completed ✓"
    body       = "Your withdrawal has been processed and funds have been sent."
    data       = {"type": "withdrawal_completed", "amount": amount, "deep_link": "/wallet"}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    _enqueue_push(user_id, title, body, data)
    _enqueue_email(user_id, "email/withdrawal_completed.html", {**payload, "title": title}, subject=title)


def handle_withdrawal_failed(payload: dict, event_id: str = "") -> None:
    """Withdrawal failed → Email + Push with reason."""
    user_id    = payload.get("user_id")
    notif_type = Notification.NotificationType.WITHDRAWAL_FAILED
    reason     = payload.get("reason", "")
    title      = "Withdrawal failed"
    body       = f"Your withdrawal could not be processed. {reason}"
    data       = {"type": "withdrawal_failed", "reason": reason, "deep_link": "/wallet"}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    _enqueue_push(user_id, title, body, data)
    _enqueue_email(user_id, "email/withdrawal_failed.html", {**payload, "title": title}, subject=title)


# ─── Review handlers ─────────────────────────────────────────────────────────

def handle_review_created(payload: dict, event_id: str = "") -> None:
    """SRS §8.14 — New review → Push to provider."""
    provider_id   = payload.get("provider_id")
    overall       = payload.get("overall_rating", "")
    notif_type    = Notification.NotificationType.REVIEW_RECEIVED
    title         = "You received a new review"
    body          = f"A client left you a {overall}★ review. Tap to see your feedback."
    data          = {
        "type":      "review_received",
        "review_id": payload.get("review_id"),
        "deep_link": f"/reviews/{payload.get('review_id')}",
    }

    _create_notification(provider_id, notif_type, title, body, data, event_id)
    _enqueue_push(provider_id, title, body, data)
    _enqueue_email(provider_id, "email/review_received.html", {**payload, "title": title}, subject=title)


def handle_review_reminder(payload: dict, event_id: str = "", days: int = 3) -> None:
    """SRS §8.14 — Review reminder at T+3 and T+10 days."""
    seeker_id  = payload.get("seeker_id")
    notif_type = Notification.NotificationType.REVIEW_REMINDER
    title      = "How was your experience?"
    body       = "Please take a moment to review your recent service."
    data       = {
        "type":           "review_reminder",
        "appointment_id": payload.get("appointment_id"),
        "deep_link":      f"/appointments/{payload.get('appointment_id')}/review",
    }

    _create_notification(seeker_id, notif_type, title, body, data, event_id)
    _enqueue_push(seeker_id, title, body, data)


def handle_review_flagged(payload: dict, event_id: str = "") -> None:
    """SRS §8.14 — Review flagged → Email to reviewer."""
    reviewer_id = payload.get("reviewer_id")
    notif_type  = Notification.NotificationType.REVIEW_FLAGGED
    title       = "Your review is under moderation"
    body        = "Your review has been flagged for moderation. You will be notified of the outcome."
    data        = {"type": "review_flagged", "review_id": payload.get("review_id"), "deep_link": "/reviews"}

    _create_notification(reviewer_id, notif_type, title, body, data, event_id)
    _enqueue_email(reviewer_id, "email/review_flagged.html", {**payload, "title": title}, subject=title)


def handle_review_removed(payload: dict, event_id: str = "") -> None:
    """SRS §8.14 — Review removed → Email to reviewer with reason."""
    reviewer_id = payload.get("reviewer_id")
    reason      = payload.get("reason", "")
    notif_type  = Notification.NotificationType.REVIEW_REMOVED
    title       = "Your review has been removed"
    body        = f"Your review was removed by our moderation team. Reason: {reason}"
    data        = {"type": "review_removed", "review_id": payload.get("review_id"), "reason": reason, "deep_link": "/reviews"}

    _create_notification(reviewer_id, notif_type, title, body, data, event_id)
    _enqueue_email(reviewer_id, "email/review_removed.html", {**payload, "title": title}, subject=title)


def handle_review_response_added(payload: dict, event_id: str = "") -> None:
    """SRS §8.14 — Provider replied to review → Push to reviewer."""
    reviewer_id = payload.get("reviewer_id")
    notif_type  = Notification.NotificationType.REVIEW_RESPONSE
    title       = "The provider replied to your review"
    body        = "A provider has posted a public response to your review."
    data        = {"type": "review_response", "review_id": payload.get("review_id"), "deep_link": f"/reviews/{payload.get('review_id')}"}

    _create_notification(reviewer_id, notif_type, title, body, data, event_id)
    _enqueue_push(reviewer_id, title, body, data)


def handle_provider_rating_low(payload: dict, event_id: str = "") -> None:
    """SRS §8.14 — Rating drops below 2.5 → Email to admin."""
    provider_id = payload.get("provider_id")
    avg         = payload.get("avg_overall")
    total       = payload.get("total_reviews")
    _notify_admins(
        title="Provider rating below threshold",
        body=f"Provider {provider_id} has an average rating of {avg} across {total} reviews.",
        data={"type": "provider_rating_low", "provider_id": provider_id, "avg_overall": avg, "deep_link": f"/admin/providers/{provider_id}"},
        event_id=event_id,
    )


# ─── Dispute handlers ─────────────────────────────────────────────────────────

def handle_dispute_raised(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — Dispute raised → Push + Email to both parties + admin."""
    seeker_id   = payload.get("seeker_id")
    provider_id = payload.get("provider_id")
    notif_type  = Notification.NotificationType.DISPUTE_RAISED
    title       = "Dispute raised"
    body        = "A dispute has been opened for your appointment. Escrow has been frozen pending resolution."
    data        = {
        "type":       "dispute_raised",
        "dispute_id": payload.get("dispute_id"),
        "deep_link":  f"/disputes/{payload.get('dispute_id')}",
    }

    for uid in filter(None, [seeker_id, provider_id]):
        _create_notification(uid, notif_type, title, body, data, event_id + f"_{uid}")
        _enqueue_push(uid, title, body, data)
        _enqueue_email(uid, "email/dispute_raised.html", {**payload, "title": title}, subject=title)

    _notify_admins(
        title="New dispute opened",
        body=f"Dispute raised for appointment {payload.get('appointment_id')}.",
        data={"type": "admin_dispute_new", "dispute_id": payload.get("dispute_id"), "deep_link": f"/admin/disputes/{payload.get('dispute_id')}"},
        event_id=event_id + "_admin",
    )


def handle_dispute_resolved(payload: dict, event_id: str = "") -> None:
    """SRS §10.1 — Dispute resolved → Push + Email to both parties."""
    seeker_id   = payload.get("seeker_id")
    provider_id = payload.get("provider_id")
    resolution  = payload.get("resolution", "")
    notes       = payload.get("resolution_notes", "")
    notif_type  = Notification.NotificationType.DISPUTE_RESOLVED
    title       = "Dispute resolved"
    body        = f"Your dispute has been resolved. Outcome: {resolution}. {notes}"
    data        = {
        "type":       "dispute_resolved",
        "dispute_id": payload.get("dispute_id"),
        "resolution": resolution,
        "deep_link":  f"/disputes/{payload.get('dispute_id')}",
    }

    for uid in filter(None, [seeker_id, provider_id]):
        _create_notification(uid, notif_type, title, body, data, event_id + f"_{uid}")
        _enqueue_push(uid, title, body, data)
        _enqueue_email(uid, "email/dispute_resolved.html", {**payload, "title": title}, subject=title)


# ─── Admin broadcast ─────────────────────────────────────────────────────────

def handle_admin_broadcast(payload: dict, event_id: str = "") -> None:
    """Admin sends a platform-wide or role-targeted push + in-app notification."""
    title        = payload.get("title", "Platform Update")
    body         = payload.get("body", "")
    target_roles = payload.get("target_roles")  # None = all users
    deep_link    = payload.get("deep_link", "/")
    data         = {"type": "broadcast", "deep_link": deep_link}

    qs = User.objects.filter(is_active=True)
    if target_roles:
        qs = qs.filter(role__in=target_roles)

    notif_type = Notification.NotificationType.SYSTEM
    for user in qs.iterator(chunk_size=500):
        uid = str(user.id)
        _create_notification(uid, notif_type, title, body, data, event_id + f"_{uid}")
        _enqueue_push(uid, title, body, data)


# ─── Internal helper: notify all admins ──────────────────────────────────────

def _notify_admins(title: str, body: str, data: dict, event_id: str = "") -> None:
    """Utility: create in-app notification + email for all admin users."""
    admins = User.objects.filter(role="admin", is_active=True)
    for admin in admins:
        _create_notification(str(admin.id), Notification.NotificationType.SYSTEM, title, body, data, event_id + f"_{admin.id}")
        _enqueue_email(str(admin.id), "email/admin_alert.html", {"title": title, "body": body, **data}, subject=title)


# ─── Handler registry ─────────────────────────────────────────────────────────

from .events import EventType

HANDLER_REGISTRY: dict[str, list[Callable]] = {
    # Accounts
    EventType.USER_VERIFICATION_REQUESTED: [handle_verification_requested],
    EventType.USER_REGISTERED:            [handle_user_registered],
    EventType.USER_EMAIL_VERIFIED:       [],   # no notification needed (verified in-flow)
    EventType.USER_PASSWORD_RESET:       [handle_password_reset_requested],
    EventType.USER_PASSWORD_CHANGED:     [handle_password_changed],
    EventType.USER_ACCOUNT_LOCKED:       [handle_account_locked],
    EventType.USER_KYC_SUBMITTED:        [handle_kyc_submitted],
    EventType.USER_KYC_APPROVED:         [handle_kyc_approved],
    EventType.USER_KYC_REJECTED:         [handle_kyc_rejected],
    # Appointments
    # EventType.APPOINTMENT_CREATED:       [handle_appointment_created],
    # EventType.APPOINTMENT_ACCEPTED:      [handle_appointment_accepted],
    # EventType.APPOINTMENT_REJECTED:      [handle_appointment_rejected],
    EventType.APPOINTMENT_STARTED:       [handle_appointment_started],
    EventType.APPOINTMENT_COMPLETED:     [handle_appointment_completed],
    EventType.APPOINTMENT_CONFIRMED:     [handle_appointment_confirmed],
    # EventType.APPOINTMENT_CANCELLED:     [handle_appointment_cancelled],
    # EventType.APPOINTMENT_EXPIRED:       [handle_appointment_expired],
    EventType.APPOINTMENT_AUTO_RELEASED: [handle_appointment_auto_released],
    EventType.APPOINTMENT_REMINDER_24H:  [lambda p, eid="": handle_appointment_reminder(p, eid, hours=24)],
    EventType.APPOINTMENT_REMINDER_2H:   [lambda p, eid="": handle_appointment_reminder(p, eid, hours=2)],
    # Payments
    EventType.WALLET_CREDITED:           [handle_wallet_credited],
    EventType.WALLET_DEBITED:             [],   # no notification for internal debit
    EventType.WITHDRAWAL_INITIATED:      [handle_withdrawal_initiated],
    EventType.WITHDRAWAL_COMPLETED:      [handle_withdrawal_completed],
    EventType.WITHDRAWAL_FAILED:         [handle_withdrawal_failed],
    EventType.ESCROW_HELD:               [],   # no user-facing notification for escrow hold
    EventType.ESCROW_RELEASED:           [],   # covered by APPOINTMENT_CONFIRMED / AUTO_RELEASED
    EventType.ESCROW_REFUNDED:           [],   # covered by APPOINTMENT_REJECTED / EXPIRED
    # Reviews
    EventType.REVIEW_CREATED:            [handle_review_created],
    EventType.REVIEW_EDITED:             [],   # no additional notification on edit
    EventType.REVIEW_FLAGGED:            [handle_review_flagged],
    EventType.REVIEW_REMOVED:            [handle_review_removed],
    EventType.REVIEW_RESPONSE_ADDED:     [handle_review_response_added],
    EventType.REVIEW_REMINDER_3D:        [lambda p, eid="": handle_review_reminder(p, eid, days=3)],
    EventType.REVIEW_REMINDER_10D:       [lambda p, eid="": handle_review_reminder(p, eid, days=10)],
    EventType.PROVIDER_RATING_LOW:       [handle_provider_rating_low],
    # Disputes
    EventType.DISPUTE_RAISED:            [handle_dispute_raised],
    EventType.DISPUTE_STATEMENT_ADDED:   [],
    EventType.DISPUTE_UNDER_REVIEW:      [],
    EventType.DISPUTE_RESOLVED:          [handle_dispute_resolved],
    # Admin
    EventType.ADMIN_BROADCAST:           [handle_admin_broadcast],
    EventType.ADMIN_KYC_PENDING:         [],   # generated inline by handle_kyc_submitted
}


def dispatch(event_type: str, payload: dict, event_id: str = "") -> int:
    """
    Route an incoming event to all registered handlers.
    Returns the number of handlers called.
    """
    handlers = HANDLER_REGISTRY.get(event_type, [])
    print(f"Dispatching {event_type}")
    if not handlers:
        logger.debug("No handlers registered for event", extra={"event_type": event_type})
        return 0

    called = 0
    for handler in handlers:
        try:
            handler(payload, event_id)
            called += 1
        except Exception as exc:
            logger.exception(
                "Handler raised an exception",
                extra={"event_type": event_type, "handler": handler.__name__ if hasattr(handler, "__name__") else str(handler), "error": str(exc)},
            )
    return called
