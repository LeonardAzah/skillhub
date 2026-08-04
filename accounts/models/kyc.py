

import uuid

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from .users import User


class KYCSubmission(models.Model):
   
    class Status(models.TextChoices):
        PENDING  = "pending",  _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="kyc_submissions"
    )

    full_name     = models.CharField(max_length=255)
    date_of_birth = models.DateField()
    nationality   = models.CharField(max_length=100)
    phone_number  = models.CharField(max_length=32)
    address       = models.TextField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    rejection_reason = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kyc_reviews",
        limit_choices_to={"role": User.Role.ADMIN},
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = _("KYC submission")
        verbose_name_plural = _("KYC submissions")
        ordering            = ["-created_at"]
        constraints = [
            # DB-enforced business rule: a user can only have ONE
            # submission that is still "in play" (pending or approved)
            # at any given time. Resubmission is only possible once the
            # previous one is rejected. This also protects against race
            # conditions two near-simultaneous submits could cause.
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(status__in=["pending", "approved"]),
                name="unique_active_kyc_submission_per_user",
            )
        ]

    def __str__(self):
        return f"KYC submission — {self.user.email} ({self.status})"

    @property
    def is_verified(self):
        return self.status == self.Status.APPROVED


class KYCDocument(models.Model):
   
    class DocumentType(models.TextChoices):
        PASSPORT       = "passport",       _("Passport")
        NATIONAL_ID    = "national_id",    _("National ID")
        DRIVER_LICENSE = "driver_license", _("Driver's License")
        SELFIE         = "selfie",         _("Selfie")
        LOCATION_PLAN  = "location_plan",  _("Location Plan / Proof of Address")

    class DocumentSide(models.TextChoices):
        FRONT  = "front",  _("Front")
        BACK   = "back",   _("Back")
        SINGLE = "single", _("Single Page")

    ID_DOCUMENT_TYPES = {
        DocumentType.PASSPORT,
        DocumentType.NATIONAL_ID,
        DocumentType.DRIVER_LICENSE,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        KYCSubmission, on_delete=models.CASCADE, related_name="documents"
    )

    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    document_side = models.CharField(
        max_length=20, choices=DocumentSide.choices, blank=True, default=""
    )
    file_url = models.URLField(
        max_length=500,
        help_text=_(
            "S3 key/URL of the uploaded document (stored after client "
            "completes presigned upload). Accessed via signed URL only — "
            "never a public link."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = _("KYC document")
        verbose_name_plural = _("KYC documents")
        ordering            = ["document_type", "document_side"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "document_type", "document_side"],
                name="unique_document_slot_per_submission",
            )
        ]

    def __str__(self):
        return f"{self.document_type} ({self.document_side or 'n/a'}) — submission {self.submission_id}"
