"""
Handler registry and dispatch.

Maps each EventType to the list of handler functions that should run for
it, and exposes dispatch(event_type, payload, event_id) which the RabbitMQ
consumer calls to route an incoming event.
"""
import logging
from typing import Callable

from utils.events import EventType

from . import accounts
from . import appointments
from . import payments
from . import reviews
from . import disputes
from . import admin

logger = logging.getLogger(__name__)

HANDLER_REGISTRY: dict[str, list[Callable]] = {
    # Accounts
    EventType.USER_VERIFICATION_REQUESTED: [accounts.handle_verification_requested],
    EventType.USER_REGISTERED:            [accounts.handle_user_registered],
    EventType.USER_EMAIL_VERIFIED:       [],   # no notification needed (verified in-flow)
    EventType.USER_PASSWORD_RESET:       [accounts.handle_password_reset_requested],
    EventType.USER_PASSWORD_CHANGED:     [accounts.handle_password_changed],
    EventType.USER_ACCOUNT_LOCKED:       [accounts.handle_account_locked],
    EventType.USER_KYC_SUBMITTED:        [accounts.handle_kyc_submitted],
    EventType.USER_KYC_APPROVED:         [accounts.handle_kyc_approved],
    EventType.USER_KYC_REJECTED:         [accounts.handle_kyc_rejected],
    # Appointments
    EventType.APPOINTMENT_CREATED:       [appointments.handle_appointment_created],
    EventType.APPOINTMENT_ACCEPTED:      [appointments.handle_appointment_accepted],
    EventType.APPOINTMENT_REJECTED:      [appointments.handle_appointment_rejected],
    EventType.APPOINTMENT_STARTED:       [appointments.handle_appointment_started],
    EventType.APPOINTMENT_COMPLETED:     [appointments.handle_appointment_completed],
    EventType.APPOINTMENT_CONFIRMED:     [appointments.handle_appointment_confirmed],
    EventType.APPOINTMENT_CANCELLED:     [appointments.handle_appointment_cancelled],
    EventType.APPOINTMENT_EXPIRED:       [appointments.handle_appointment_expired],
    EventType.APPOINTMENT_AUTO_RELEASED: [appointments.handle_appointment_auto_released],
    EventType.APPOINTMENT_REMINDER_24H:  [lambda p, eid="": appointments.handle_appointment_reminder(p, eid, hours=24)],
    EventType.APPOINTMENT_REMINDER_2H:   [lambda p, eid="": appointments.handle_appointment_reminder(p, eid, hours=2)],
    # Payments
    EventType.WALLET_CREDITED:           [payments.handle_wallet_credited],
    EventType.WALLET_DEBITED:             [],   # no notification for internal debit
    EventType.WITHDRAWAL_INITIATED:      [payments.handle_withdrawal_initiated],
    EventType.WITHDRAWAL_COMPLETED:      [payments.handle_withdrawal_completed],
    EventType.WITHDRAWAL_FAILED:         [payments.handle_withdrawal_failed],
    EventType.ESCROW_HELD:               [],   # no user-facing notification for escrow hold
    EventType.ESCROW_RELEASED:           [],   # covered by APPOINTMENT_CONFIRMED / AUTO_RELEASED
    EventType.ESCROW_REFUNDED:           [],   # covered by APPOINTMENT_REJECTED / EXPIRED
    # Reviews
    EventType.REVIEW_CREATED:            [reviews.handle_review_created],
    EventType.REVIEW_EDITED:             [],   # no additional notification on edit
    EventType.REVIEW_FLAGGED:            [reviews.handle_review_flagged],
    EventType.REVIEW_REMOVED:            [reviews.handle_review_removed],
    EventType.REVIEW_RESPONSE_ADDED:     [reviews.handle_review_response_added],
    EventType.REVIEW_REMINDER_3D:        [lambda p, eid="": reviews.handle_review_reminder(p, eid, days=3)],
    EventType.REVIEW_REMINDER_10D:       [lambda p, eid="": reviews.handle_review_reminder(p, eid, days=10)],
    EventType.PROVIDER_RATING_LOW:       [reviews.handle_provider_rating_low],
    # Disputes
    EventType.DISPUTE_RAISED:            [disputes.handle_dispute_raised],
    EventType.DISPUTE_STATEMENT_ADDED:   [],
    EventType.DISPUTE_UNDER_REVIEW:      [],
    EventType.DISPUTE_RESOLVED:          [disputes.handle_dispute_resolved],
    # Admin
    EventType.ADMIN_BROADCAST:           [admin.handle_admin_broadcast],
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
