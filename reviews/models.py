import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ._help import _validate_half_step
from .constants import WEIGHT_COMMUNICATION, WEIGHT_PUNCTUALITY, WEIGHT_QUALITY, EDIT_WINDOW_HOURS, RESPONSE_WINDOW_DAYS

class Review(models.Model):
    """
    A seeker's structured review of a provider after an appointment reaches terminal status.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(
        "appointments.Appointment",
        on_delete=models.PROTECT,
        related_name="review",
    )

    reviewer = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="reviews_given",
    )

    provider = models.ForeignKey(
        "accounts.ProviderProfile",
        on_delete=models.PROTECT,
        related_name="reviews_received",
    )

    communication_rating = models.DecimalField(
        max_digits=2, decimal_places=1,
        validators=[_validate_half_step],
    )

    punctuality_rating = models.DecimalField(
        max_digits=2, decimal_places=1,
        validators=[_validate_half_step],
    )

    quality_rating = models.DecimalField (
        max_digits=2, decimal_places=1,
        validators=[_validate_half_step],
    )

    overall_rating = models.DecimalField(
        max_digits=4, decimal_places=2,
        editable=False,
    )

    comment = models.TextField(
        blank=True, default="",
        max_length=1000,
    )

    is_flagged = models.BooleanField(default=False, db_index=True)
    flag_reason = models.TextField(blank=True, default="")
    is_visible = models.BooleanField(
        default=True, db_index=True
    )

    provider_response = models.TextField(
        blank=True, default="", max_length=500,
    )

    provider_response_at= models.DateTimeField(null=True, blank=True)

    edit_locked_at = models.DateTimeField(
        null=True, blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True
    )
    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        verbose_name = _("review")
        verbose_name_plural = _("reviews")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "is_visible", "-created_at"]),
            models.Index(fields=["reviewer"]),
            models.Index(fields=["is_flagged"]),
        ]

    def _compute_overall(self) -> Decimal:
        """Weighted average rounded to 2 dp."""
        raw = (
            Decimal(str(self.communication_rating)) * WEIGHT_COMMUNICATION
            + Decimal(str(self.punctuality_rating)) * WEIGHT_PUNCTUALITY
            + Decimal(str(self.quality_rating)) * WEIGHT_QUALITY
        )

        return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        self.overall_rating = self._compute_overall()
        if not self.edit_locked_at:
            self.edit_locked_at = timezone.now() + timezone.timedelta(hours=EDIT_WINDOW_HOURS)
        super().save(*args, **kwargs)

    @property
    def is_editable(self) -> bool:
        """Edits allowed within 24h of submission."""
        if not self.edit_locked_at:
            return True
        return timezone.now() < self.edit_locked_at

    def __str__(self):
        return (
            f"Review[{self.overall_rating}★] "
            f"{self.reviewer.email} → {self.provider.user.email}"
        )


class ProviderReviewSummary(models.Model):
    """
    Denormalised aggregate cache to avoid expensive aggregations on every profile load.
    Updated asynchronously after each review event.

    SLA: recalculated within 30 seconds of review submission.
    """
    provider= models.OneToOneField(
        "accounts.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="review_summary",
    )
    total_reviews = models.PositiveIntegerField(default=0)
    avg_communication = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    avg_punctuality = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    avg_quality = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))
    avg_overall = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.00"))

    star_distribution = models.JSONField(
        default=dict
    )
    last_upated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("provider review summary")
        verbose_name_plural = _("provider review summaries")

    def __str__(self):
        return f"Summary ({self.provider.user.email}) {self.avg_overall} / {self.total_reviews} reviews"

class ReviewAuditLog(models.Model):
    """Immutable record of every admin moderation action for accountability and audit purposes."""

    class Action(models.TextChoices):
        FLAGGED = "flagged"
        UNFLAGGED = "unflagged"
        REMOVED = "removed"
        RESTORED = "restored"
        RESPONSE_REMOVED = "response_removed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey(
        Review,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )

    review_id_snapshot = models.UUIDField()
    action = models.CharField(max_length=20, choices=Action.choices)
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        related_name="review_audit_actions",
        null=True,
    )
    reason = models.TextField(blank=True, default="")
    diff = models.JSONField(
        default=dict,
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("review audit log")
        verbose_name_plural = _("review audit logs")
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.action}] review {self.review_id_snapshot} by {self.actor}"
