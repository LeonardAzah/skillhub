"""
Review lifecycle event handlers.

Covers: new reviews, review reminders, moderation (flag/remove),
provider responses, and low-rating admin alerts.
"""
from notifications.models import Notification
from notifications._helper import _create_notification, _enqueue_push, _enqueue_email, _notify_admins


def handle_review_created(payload: dict, event_id: str = "") -> None:
    """New review → Push to provider."""
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
    """Review reminder at T+3 and T+10 days."""
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
    """Review flagged → Email to reviewer."""
    reviewer_id = payload.get("reviewer_id")
    notif_type  = Notification.NotificationType.REVIEW_FLAGGED
    title       = "Your review is under moderation"
    body        = "Your review has been flagged for moderation. You will be notified of the outcome."
    data        = {"type": "review_flagged", "review_id": payload.get("review_id"), "deep_link": "/reviews"}

    _create_notification(reviewer_id, notif_type, title, body, data, event_id)
    _enqueue_email(reviewer_id, "email/review_flagged.html", {**payload, "title": title}, subject=title)


def handle_review_removed(payload: dict, event_id: str = "") -> None:
    """Review removed → Email to reviewer with reason."""
    reviewer_id = payload.get("reviewer_id")
    reason      = payload.get("reason", "")
    notif_type  = Notification.NotificationType.REVIEW_REMOVED
    title       = "Your review has been removed"
    body        = f"Your review was removed by our moderation team. Reason: {reason}"
    data        = {"type": "review_removed", "review_id": payload.get("review_id"), "reason": reason, "deep_link": "/reviews"}

    _create_notification(reviewer_id, notif_type, title, body, data, event_id)
    _enqueue_email(reviewer_id, "email/review_removed.html", {**payload, "title": title}, subject=title)


def handle_review_response_added(payload: dict, event_id: str = "") -> None:
    """Provider replied to review → Push to reviewer."""
    reviewer_id = payload.get("reviewer_id")
    notif_type  = Notification.NotificationType.REVIEW_RESPONSE
    title       = "The provider replied to your review"
    body        = "A provider has posted a public response to your review."
    data        = {"type": "review_response", "review_id": payload.get("review_id"), "deep_link": f"/reviews/{payload.get('review_id')}"}

    _create_notification(reviewer_id, notif_type, title, body, data, event_id)
    _enqueue_push(reviewer_id, title, body, data)


def handle_provider_rating_low(payload: dict, event_id: str = "") -> None:
    """Rating drops below 2.5 → Email to admin."""
    provider_id = payload.get("provider_id")
    avg         = payload.get("avg_overall")
    total       = payload.get("total_reviews")
    _notify_admins(
        title="Provider rating below threshold",
        body=f"Provider {provider_id} has an average rating of {avg} across {total} reviews.",
        data={"type": "provider_rating_low", "provider_id": provider_id, "avg_overall": avg, "deep_link": f"/admin/providers/{provider_id}"},
        event_id=event_id,
    )
