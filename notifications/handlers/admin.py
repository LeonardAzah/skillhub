"""
Admin-initiated event handlers.

Covers platform-wide or role-targeted broadcast notifications.
"""
from accounts.models import User
from notifications.models import Notification
from notifications._helper import _create_notification, _enqueue_push


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
