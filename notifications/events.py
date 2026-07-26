"""
Single source of truth for every domain event published onto RabbitMQ.

Architecture
────────────
Every module (accounts, appointments, payments, reviews, disputes) calls
`publish_event(event_type, payload)` to drop a message onto the
`boloconnect.events` exchange (topic type).  The notification worker
subscribes to that exchange via the `boloconnect.notifications` queue and
routes each event_type to the correct handler.

Routing key convention:  <domain>.<entity>.<action>
  e.g.  accounts.user.registered
        appointments.appointment.accepted
        payments.wallet.credited

SRS §10.1 — Notification Types catalogue
SRS §8.14 — Review module notification events
"""
from dataclasses import dataclass, field
from typing import Any


# ─── Event type constants ─────────────────────────────────────────────────────

class EventType:
    """All event routing keys published by any module."""

    # ── Accounts / Auth ───────────────────────────────────────────────────────
    USER_REGISTERED            = "accounts.user.registered"
    USER_VERIFICATION_REQUESTED = "accounts.user.verification_requested"
    USER_EMAIL_VERIFIED          = "accounts.user.email_verified"
    USER_PASSWORD_RESET        = "accounts.user.password_reset"
    USER_PASSWORD_CHANGED      = "accounts.user.password_changed"
    USER_ACCOUNT_LOCKED        = "accounts.user.account_locked"
    USER_KYC_SUBMITTED         = "accounts.user.kyc_submitted"
    USER_KYC_APPROVED          = "accounts.user.kyc_approved"
    USER_KYC_REJECTED          = "accounts.user.kyc_rejected"

    # ── Appointments ─────────────────────────────────────────────────────────
    APPOINTMENT_CREATED        = "appointments.appointment.created"       # New booking (PENDING)
    APPOINTMENT_ACCEPTED       = "appointments.appointment.accepted"
    APPOINTMENT_REJECTED       = "appointments.appointment.rejected"
    APPOINTMENT_STARTED        = "appointments.appointment.started"       # IN_PROGRESS
    APPOINTMENT_COMPLETED      = "appointments.appointment.completed"     # provider marks done
    APPOINTMENT_CONFIRMED      = "appointments.appointment.confirmed"     # seeker confirms
    APPOINTMENT_CANCELLED      = "appointments.appointment.cancelled"
    APPOINTMENT_EXPIRED        = "appointments.appointment.expired"       # 24h no provider response
    APPOINTMENT_AUTO_RELEASED  = "appointments.appointment.auto_released" # 48h no seeker response
    APPOINTMENT_REMINDER_24H   = "appointments.appointment.reminder_24h"
    APPOINTMENT_REMINDER_2H    = "appointments.appointment.reminder_2h"

    # ── Payments / Wallet ─────────────────────────────────────────────────────
    WALLET_CREDITED            = "payments.wallet.credited"               # cash-in success
    WALLET_DEBITED             = "payments.wallet.debited"
    WITHDRAWAL_INITIATED       = "payments.withdrawal.initiated"
    WITHDRAWAL_COMPLETED       = "payments.withdrawal.completed"
    WITHDRAWAL_FAILED          = "payments.withdrawal.failed"
    ESCROW_HELD                = "payments.escrow.held"
    ESCROW_RELEASED            = "payments.escrow.released"
    ESCROW_REFUNDED            = "payments.escrow.refunded"

    # ── Reviews ───────────────────────────────────────────────────────────────
    REVIEW_CREATED             = "reviews.review.created"
    REVIEW_EDITED              = "reviews.review.edited"
    REVIEW_FLAGGED             = "reviews.review.flagged"                 # admin flagged
    REVIEW_REMOVED             = "reviews.review.removed"                 # admin removed
    REVIEW_RESPONSE_ADDED      = "reviews.review.response_added"         # provider replied
    REVIEW_REMINDER_3D         = "reviews.review.reminder_3d"            # T+3 reminder
    REVIEW_REMINDER_10D        = "reviews.review.reminder_10d"           # T+10 final reminder
    PROVIDER_RATING_LOW        = "reviews.provider.rating_low"           # drops below 2.5

    # ── Disputes ──────────────────────────────────────────────────────────────
    DISPUTE_RAISED             = "disputes.dispute.raised"
    DISPUTE_STATEMENT_ADDED    = "disputes.dispute.statement_added"
    DISPUTE_UNDER_REVIEW       = "disputes.dispute.under_review"
    DISPUTE_RESOLVED           = "disputes.dispute.resolved"

    # ── Admin / Platform ──────────────────────────────────────────────────────
    ADMIN_BROADCAST            = "admin.platform.broadcast"
    ADMIN_KYC_PENDING          = "admin.kyc.pending"                      # admin alert

    @classmethod
    def all_events(cls) -> list[str]:
        return [
            v for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, str) and "." in v
        ]


# ─── Envelope ─────────────────────────────────────────────────────────────────

@dataclass
class Event:
    """
    Standard event envelope for every message on the bus.

    Fields
    ──────
    event_type  : routing key (see EventType constants)
    payload     : domain-specific dict — schema documented per handler
    event_id    : UUIDv4, used for idempotency
    occurred_at : ISO-8601 UTC timestamp of the originating action
    version     : schema version for forward-compat
    """
    event_type:  str
    payload:     dict = field(default_factory=dict)
    event_id:    str  = field(default_factory=lambda: __import__("uuid").uuid4().hex)
    occurred_at: str  = field(default_factory=lambda: __import__("datetime").datetime.utcnow().isoformat() + "Z")
    version:     str  = "1.0"

    def to_dict(self) -> dict:
        return {
            "event_id":   self.event_id,
            "event_type": self.event_type,
            "payload":    self.payload,
            "occurred_at":self.occurred_at,
            "version":    self.version,
        }


# ─── Payload schemas (documented for consumers) ───────────────────────────────

"""
accounts.user.registered
  { user_id, email, username }

accounts.user.email_verified
  { user_id, email }

accounts.user.kyc_submitted
  { user_id, email, document_type }

accounts.user.kyc_approved / kyc_rejected
  { user_id, email, reason? }

accounts.user.account_locked
  { user_id, email, lockout_minutes }

appointments.appointment.created
  { appointment_id, provider_id, seeker_id, category, scheduled_date,
    scheduled_time, location_address, quoted_price }

appointments.appointment.accepted / rejected / started / completed /
confirmed / cancelled / expired / auto_released
  { appointment_id, provider_id, seeker_id, status, reason? }

appointments.appointment.reminder_24h / reminder_2h
  { appointment_id, provider_id, seeker_id, scheduled_date, scheduled_time }

payments.wallet.credited
  { user_id, amount, currency, transaction_id, new_balance }

payments.withdrawal.initiated / completed / failed
  { user_id, amount, currency, transaction_id, reason? }

payments.escrow.held / released / refunded
  { appointment_id, seeker_id, provider_id, amount, transaction_id }

reviews.review.created / edited
  { review_id, appointment_id, provider_id, reviewer_id,
    overall_rating, comment? }

reviews.review.flagged / removed
  { review_id, provider_id, reviewer_id, reason }

reviews.review.response_added
  { review_id, provider_id, reviewer_id, response_text }

reviews.review.reminder_3d / reminder_10d
  { appointment_id, seeker_id, provider_id }

reviews.provider.rating_low
  { provider_id, avg_overall, total_reviews }

disputes.dispute.raised
  { dispute_id, appointment_id, seeker_id, provider_id, seeker_statement }

disputes.dispute.statement_added
  { dispute_id, appointment_id, submitted_by, role }

disputes.dispute.under_review / resolved
  { dispute_id, appointment_id, seeker_id, provider_id,
    resolution?, resolution_notes? }

admin.platform.broadcast
  { title, body, target_roles?, deep_link? }

admin.kyc.pending
  { user_id, email, document_count }
"""
