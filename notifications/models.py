from django.db import models

# Create your models here.
"""
SkillHub - notifications/models.py

Models
──────
Notification              — in-app notification record
NotificationPreference    — per-user channel preferences
EmailLog                  — audit log for every transactional email
"""
import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    """Persisted in-app notification."""

    class NotificationType(models.TextChoices):
        # Auth / Account
        ACCOUNT_VERIFIED        = "account_verified",        _("Account Verified")
        KYC_SUBMITTED           = "kyc_submitted",           _("KYC Submitted")
        KYC_APPROVED            = "kyc_approved",            _("KYC Approved")
        KYC_REJECTED            = "kyc_rejected",            _("KYC Rejected")
        # Appointments
        BOOKING_REQUEST         = "booking_request",         _("New Booking Request")
        BOOKING_ACCEPTED        = "booking_accepted",        _("Booking Accepted")
        BOOKING_REJECTED        = "booking_rejected",        _("Booking Rejected")
        JOB_STARTED             = "job_started",             _("Job Started")
        JOB_COMPLETED           = "job_completed",           _("Job Completed")
        JOB_CONFIRMED           = "job_confirmed",           _("Job Confirmed")
        BOOKING_CANCELLED       = "booking_cancelled",       _("Booking Cancelled")
        BOOKING_EXPIRED         = "booking_expired",         _("Booking Expired")
        ESCROW_AUTO_RELEASED    = "escrow_auto_released",    _("Escrow Auto-Released")
        REMINDER_24H            = "reminder_24h",            _("Appointment Reminder 24h")
        REMINDER_2H             = "reminder_2h",             _("Appointment Reminder 2h")
        # Payments
        WALLET_CREDITED         = "wallet_credited",         _("Wallet Credited")
        WITHDRAWAL_INITIATED    = "withdrawal_initiated",    _("Withdrawal Initiated")
        WITHDRAWAL_COMPLETED    = "withdrawal_completed",    _("Withdrawal Completed")
        WITHDRAWAL_FAILED       = "withdrawal_failed",       _("Withdrawal Failed")
        # Reviews
        REVIEW_RECEIVED         = "review_received",         _("Review Received")
        REVIEW_REMINDER         = "review_reminder",         _("Review Reminder")
        REVIEW_FLAGGED          = "review_flagged",          _("Review Flagged")
        REVIEW_REMOVED          = "review_removed",          _("Review Removed")
        REVIEW_RESPONSE         = "review_response",         _("Provider Replied to Review")
        # Disputes
        DISPUTE_RAISED          = "dispute_raised",          _("Dispute Raised")
        DISPUTE_RESOLVED        = "dispute_resolved",        _("Dispute Resolved")
        # Generic
        SYSTEM                  = "system",                  _("System")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )
    notification_type = models.CharField(
        max_length=40,
        choices=NotificationType.choices,
        db_index=True,
    )
    title   = models.CharField(max_length=200)
    body    = models.TextField()
    data    = models.JSONField(
        default=dict,
        help_text="Structured JSON payload for deep-linking in the Flutter app.",
    )
    is_read = models.BooleanField(default=False, db_index=True)
    # Source event — for audit / idempotency
    event_id   = models.CharField(max_length=64, blank=True, db_index=True)
    event_type = models.CharField(max_length=80, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("notification")
        verbose_name_plural = _("notifications")
        ordering            = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.notification_type}] {self.user.email} — {self.title[:40]}"


class NotificationPreference(models.Model):
    """
    Per-user, per-notification-type channel opt-in/opt-out.
    Default is push=True, email=True for all types.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    notification_type = models.CharField(
        max_length=40,
        choices=Notification.NotificationType.choices,
    )
    push_enabled  = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "notification_type")]
        verbose_name         = _("notification preference")
        verbose_name_plural  = _("notification preferences")

    def __str__(self):
        return (
            f"{self.user.email} — {self.notification_type} "
            f"(push={self.push_enabled}, email={self.email_enabled})"
        )


class EmailLog(models.Model):
    """
    Audit log for every transactional email dispatched.
    """

    class Status(models.TextChoices):
        SENT        = "sent",       _("Sent")
        DELIVERED   = "delivered",  _("Delivered")
        BOUNCED     = "bounced",    _("Bounced")
        COMPLAINED  = "complained", _("Spam Complaint")
        FAILED      = "failed",     _("Failed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_logs",
    )
    to_email  = models.EmailField(db_index=True)
    subject   = models.CharField(max_length=300)
    template  = models.CharField(max_length=100)
    status    = models.CharField(max_length=15, choices=Status.choices, default=Status.SENT)
    event_id  = models.CharField(max_length=64, blank=True)
    ses_message_id = models.CharField(max_length=200, blank=True)
    error_detail   = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("email log")
        verbose_name_plural = _("email logs")
        ordering            = ["-created_at"]

    def __str__(self):
        return f"Email [{self.status}] → {self.to_email}: {self.subject[:50]}"
