from django.db import models

"""
Models
──────
Dispute         — the dispute record and its lifecycle
DisputeEvidence — files (images/video/documents) uploaded by either party
DisputeAuditLog — immutable log of every action, retained for 7 years 

Lifecycle
─────────
OPEN
-> Seeker raise dispute; escrow frozen.
-> Provider has 48H to submit statement + evidence.
UNDER_REVIEW
-> Admin picks up the case
RESOLVED_SEEKER     (terminal) -> full refund to seeker
RESOLVED_PROVIDER   (terminal) -> full erscrow release to provider
CLOSED              (terminal) -> admin closed without financial change (rare)

Resolution outcomes:
REFUND_SEEKER  -> payments.refund_escrow(full)
RELEASE_PROVIDER ->payments.release_escrow
SPLIT -> payments.refund_escrow(partial)
"""
import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from .constants import PROVIDER_STATEMENT_DEADLINE_HOURS, DISPUTE_RAISE_WINDOW_HOURS

class Dispute(models.Model):
    """
    Core dispute recored
    OneToOne with Appointment: exactly one dispute per appointment.
    """

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        UNDER_REVIEW = "under_review", _("Under Review")
        RESOLVED_SEEKER = "resolved_seeker", _("Resolved - Seeker")
        RESOLVED_PROVIDER = "resolved_provider", _("Resolved - Provider")
        CLOSED = "closed", _("Closed")

    class Resolution(models.TextChoices):
        REFUND_SEEKER = "refund_seeker", _("Full Refund to Seeker")
        RELEASE_PROVIDER = "release_provider", _("Release to Provider")
        SPLIT = "split", _("Split Between Parties")

    TERMINAL_STATUSES = {
            Status.RESOLVED_SEEKER,
            Status.RESOLVED_PROVIDER,
            Status.CLOSED,
        }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    appointment = models.OneToOneField(
        "appointments.Appointment",
        on_delete=models.PROTECT,
        related_name="dispute"
    )

    raised_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="disputes_raised",
    )

    seeker_statement = models.TextField()
    provider_statement = models.TextField()
    provider_statement_at = models.DateTimeField(null=True, blank=True)

    admin_notes = models.TextField(blank=True, default="")
    resolution = models.CharField(max_length=20, choices=Resolution.choices, null=True, blank=True)

    resolution_notes = models.TextField(blank=True, default="")
    split_percent_seeker = models.PositiveBigIntegerField(
        null=True,
        blank=True
    )

    resolved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disputes_resolved",
        limit_choices_to={"is_Staff": True},
    )

    resolved_at= models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("dispute")
        verbose_name_plural = _("disputes")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"])
        ]

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    @property
    def provider_statement_deadline(self):
        """Provider has 48 h from dispute creation to submit statement."""
        from datetime import timedelta
        return self.created_at + timedelta(hours=PROVIDER_STATEMENT_DEADLINE_HOURS)
    
    def __str__(self):
        return f"Dispute[{self.status}] apt={str(self.appointment_id)[:8]}"

class DisputeEvidence(models.Model):
    """
    File evidence uploaded by either party during an open dispute.
    Both parties may upload up to 20mb per file
    """

    class FileType(models.TextChoices):
        IMAGE = "image", _("Image")
        VIDEO = "video", _("Video")
        DOCUMENT = "document", _("Document")

    id = models.UUIDField(primary_key=True,default=uuid.uuid4 ,editable=False)
    dispute = models.ForeignKey(
        Dispute,
        on_delete=models.CASCADE,
        related_name="evidence",
    )
    uploaded_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="dispute_evidence"
    )
    file_url = models.URLField()
    file_type = models.CharField(max_length=10, choices=FileType.choices)
    description = models.CharField(
        max_length=500,
        blank=True,
        default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("dispute evidence")
        verbose_name_plural = _("dispute evidence")
        ordering = ["created_at"]

    def __str__(self):
        return f"Evidence[{self.file_type}] dispute={str(self.dispute_id)[:8]}"

class DisputeAuditLog(models.Model):
    """
    Immutable audit trail for every action on a dispute.
    Retained for 7 years per financial complaince.
    """

    class Action(models.TextChoices):
        RAISED = "raised", _("Dispute Raised")
        STATEMENT_SEEKER= "statement_seeker", _("Seeker Statement Added")
        STATEMENT_PROVIDER = "statement_provider", _("Provider Statement Added")
        EVIDENCE_UPLOADED = "evidence_uploaded", _("Evidence Uploaded")
        MARKED_UNDER_REVIEW= "under_review", _("Marked Under Review")
        RESOLVED = "resolved", _("Resolved")
        CLOSED = "closed", _("Closed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dispute = models.ForeignKey(
        Dispute,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    dispute_id_snapshot = models.UUIDField()
    action = models.CharField(max_length=20, choices=Action.choices)
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="dispute_audit_actions",
    )
    actor_role = models.CharField(
        max_length=10,
        blank=True,
        default=""
    )
    description = models.TextField(blank=True, default="")
    diff = models.JSONField(
        default=dict
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("dispute audit log")
        verbose_name_plural = _("dispute audit logs")
        ordering = ["timestamp"]

    def __str__(self):
        return (
            f"[{self.action}] dispute={str(self.dispute_id_snapshot)[:8]}"
            f"by {self.actor}"
        )