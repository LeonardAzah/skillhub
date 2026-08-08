"""
Models
──────
Appointment          — core booking record with full state-machine lifecycle
ProviderAvailability — blocked time slots set by the provider
AppointmentStatusLog — immutable audit trail of every status transition

Note: The wallet PIN lives in payments/models.py (WalletPin).
      It is a payment-domain concern that gates escrow, withdrawal, and
      any financial action. The booking flow checks for a short-lived
      cache token (`wallet_pin_verified:{seeker_id}`) that the payments
      module writes after the seeker enters their PIN.
"""
import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ProviderAvailability(models.Model):
    """
    Time slots that a provider has explicitly blocked (holiday, personal time).
    Available-slot algorithm: all 1-hour slots from 07:00–19:00 that are NOT
    in this table AND NOT already booked by an active appointment are available.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        "accounts.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="blocked_slots",
    )
    blocked_date  = models.DateField(db_index=True)
    blocked_start = models.TimeField()
    blocked_end   = models.TimeField()
    reason        = models.CharField(max_length=200, blank=True, default="")
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("provider availability block")
        verbose_name_plural = _("provider availability blocks")
        ordering = ["blocked_date", "blocked_start"]

    def __str__(self):
        return f"{self.provider} blocked {self.blocked_date} {self.blocked_start}–{self.blocked_end}"


class Appointment(models.Model):
    """
    Core booking record
    Full lifecycle from PENDING → terminal state.
    """

    class Status(models.TextChoices):
        PENDING        = "pending",        _("Pending")          # awaiting provider acceptance
        ACCEPTED       = "accepted",       _("Accepted")         # provider confirmed
        REJECTED       = "rejected",       _("Rejected")         # provider declined
        IN_PROGRESS    = "in_progress",    _("In Progress")      # provider started
        COMPLETED      = "completed",      _("Completed")        # provider finished
        CONFIRMED      = "confirmed",      _("Confirmed")        # seeker satisfied
        AUTO_RELEASED  = "auto_released",  _("Auto-Released")    # 48h seeker timeout
        DISPUTED       = "disputed",       _("Disputed")         # seeker raised dispute
        CANCELLED      = "cancelled",      _("Cancelled")        # either party cancelled
        EXPIRED        = "expired",        _("Expired")          # 24h no provider response

    # allowed state transitions
    ALLOWED_TRANSITIONS: dict[str, list[str]] = {
        Status.PENDING:       [Status.ACCEPTED, Status.REJECTED, Status.CANCELLED, Status.EXPIRED],
        Status.ACCEPTED:      [Status.IN_PROGRESS, Status.CANCELLED],
        Status.IN_PROGRESS:   [Status.COMPLETED],
        Status.COMPLETED:     [Status.CONFIRMED, Status.AUTO_RELEASED, Status.DISPUTED],
        Status.CONFIRMED:     [],
        Status.AUTO_RELEASED: [],
        Status.DISPUTED:      [Status.CONFIRMED, Status.AUTO_RELEASED],
        Status.REJECTED:      [],
        Status.CANCELLED:     [],
        Status.EXPIRED:       [],
    }

    TERMINAL_STATUSES = {Status.CONFIRMED, Status.AUTO_RELEASED, Status.REJECTED,
                         Status.CANCELLED, Status.EXPIRED}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    provider = models.ForeignKey(
        "accounts.ProviderProfile",
        on_delete=models.PROTECT,
        related_name="appointments_as_provider",
    )
    customer = models.ForeignKey(
        "accounts.SeekerProfile",
        on_delete=models.PROTECT,
        related_name="appointments_as_customer",
    )
    category = models.ForeignKey(
        "categories.Category",
        on_delete=models.PROTECT,
        related_name="appointments",
    )

    location_address = models.TextField(
        help_text=_("Human-readable service address.")
    )
    location_lat = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text=_("Latitude of service location (PostGIS Point in production)."),
    )
    location_lng = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
    )

    scheduled_at = models.DateTimeField(db_index=True)

    notes = models.TextField(
        blank=True, default="",
        help_text=_("Special instructions from the seeker."),
    )
    quoted_price = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text=_("Price agreed at booking time. Moved into escrow on creation."),
    )
    final_price  = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text=_("Actual final price. May differ from quoted_price."),
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    cancellation_reason = models.TextField(blank=True, default="")

    completion_proof = models.URLField(
        blank=True, default="",
        help_text=_("S3 URL of provider-uploaded completion photo/video."),
    )
    completion_notes = models.TextField(blank=True, default="")

    # Linked financial record (set by payment module)
    escrow_transaction_id = models.UUIDField(
        null=True, blank=True,
        help_text=_("ID of the escrow Transaction created by the payments module."),
    )

    # Reminder tracking
    reminder_sent_24h = models.BooleanField(default=False)
    reminder_sent_2h  = models.BooleanField(default=False)

    # Timestamps
    accepted_at  = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("appointment")
        verbose_name_plural = _("appointments")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["status", "completed_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.ALLOWED_TRANSITIONS.get(self.status, [])

    def transition_to(self, new_status: str, actor=None, reason: str = "") -> None:
        """
        Apply a status transition, stamp the relevant timestamp,
        and append to the immutable status log.
        Raises ValueError on illegal transition.
        """
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Cannot transition appointment from '{self.status}' to '{new_status}'."
            )

        now = timezone.now()
        update_fields = ["status", "updated_at"]
        old_status = self.status

        if new_status == self.Status.ACCEPTED:
            self.accepted_at = now
            update_fields.append("accepted_at")
        elif new_status == self.Status.COMPLETED:
            self.completed_at = now
            update_fields.append("completed_at")
        elif new_status in (self.Status.CONFIRMED, self.Status.AUTO_RELEASED):
            self.confirmed_at = now
            update_fields.append("confirmed_at")
        elif new_status == self.Status.CANCELLED:
            self.cancelled_at = now
            self.cancellation_reason = reason
            update_fields += ["cancelled_at", "cancellation_reason"]

        self.status = new_status
        self.save(update_fields=update_fields)

        AppointmentStatusLog.objects.create(
            appointment=self,
            from_status=old_status,
            to_status=new_status,
            actor_id=str(actor.id) if actor else None,
            reason=reason,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    def __str__(self):
        return (
            f"Appointment #{str(self.id)[:8]} "
            f"[{self.status}] {self.customer} → {self.provider}"
        )


class AppointmentStatusLog(models.Model):
    """
    Immutable audit trail of every status transition.
    Written by Appointment.transition_to(); never mutated directly.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="status_logs",
    )
    from_status = models.CharField(max_length=15, blank=True)
    to_status   = models.CharField(max_length=15)
    actor_id    = models.CharField(
        max_length=36, blank=True, null=True, default=None,
        help_text=_("UUID of the User who triggered the transition."),
    )
    reason    = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("appointment status log")
        verbose_name_plural = _("appointment status logs")
        ordering = ["timestamp"]

    def __str__(self):
        return f"[{self.appointment_id}] {self.from_status} → {self.to_status}"
