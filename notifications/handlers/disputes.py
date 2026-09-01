"""
Dispute lifecycle event handlers.

Covers: a dispute being raised (notifying both parties + admins) and a
dispute being resolved (notifying both parties).
"""
from notifications.models import Notification
from notifications._helper import _create_notification, _enqueue_push, _enqueue_email, _notify_admins


def handle_dispute_raised(payload: dict, event_id: str = "") -> None:
    """Dispute raised → Push + Email to both parties + admin."""
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
    """Dispute resolved → Push + Email to both parties."""
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
