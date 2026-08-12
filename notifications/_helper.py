import logging

from .models import Notification
from accounts.models import User



logger = logging.getLogger(__name__)


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


def _notify_admins(title: str, body: str, data: dict, event_id: str = "") -> None:
    """Utility: create in-app notification + email for all admin users."""
    admins = User.objects.filter(role="admin", is_active=True)
    for admin in admins:
        _create_notification(str(admin.id), Notification.NotificationType.SYSTEM, title, body, data, event_id + f"_{admin.id}")
        _enqueue_email(str(admin.id), "email/admin_alert.html", {"title": title, "body": body, **data}, subject=title)