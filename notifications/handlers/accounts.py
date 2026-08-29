"""
Account event handlers.

Covers: verification, password reset/change, registration, KYC submission
review, and account lockouts.
"""
from notifications.models import Notification
from notifications._helper import _create_notification, _enqueue_push, _enqueue_email, _check_preference, _notify_admins


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
        subject="Reset your SkillHub password",
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
    """KYC submitted → Push to user, Email to admin."""
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
    """KYC approved → Email + Push."""
    user_id    = payload.get("user_id")
    notif_type = Notification.NotificationType.KYC_APPROVED
    title      = "Identity verified ✓"
    body       = "Your identity has been verified. You can now accept bookings."
    data       = {"type": "kyc_approved", "deep_link": "/profile"}

    _create_notification(user_id, notif_type, title, body, data, event_id)
    _enqueue_push(user_id, title, body, data)
    _enqueue_email(user_id, "email/kyc_approved.html", {"user_id": user_id}, subject=title)


def handle_kyc_rejected(payload: dict, event_id: str = "") -> None:
    """KYC rejected → Email + Push with reason."""
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
    """Account locked → Email alert."""
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
        subject="Your SkillHub password has been changed",
    )
