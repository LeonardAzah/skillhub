"""
Wallet / withdrawal notification handlers.

(These notify users about wallet and withdrawal state changes; they are
distinct from the `payments` app's own Celery tasks, which handle the
actual escrow/ledger side effects.)
"""
from notifications.models import Notification
from notifications._helper import _create_notification, _enqueue_push, _enqueue_email


def handle_wallet_credited(payload: dict, event_id: str = "") -> None:
    """Wallet top-up → Email + Push."""
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
    """Withdrawal initiated → Email + Push."""
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
    """Withdrawal completed → Email + Push."""
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
