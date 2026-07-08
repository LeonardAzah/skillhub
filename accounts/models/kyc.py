import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from .users import User


class KYCDocument(models.Model):
    """
    KYC identity verification documents.
    Stored in private S3 bucket or cloudinary with server-side encryption.
    """

    class DocumentType(models.TextChoices):
        PASSPORT = "passport", _("Passport")
        NATIONAL_ID = "national_id", _("National ID")
        DRIVER_LICENSE = "driver_license", _("Driver's License")
        OTHER = "other", _("Other")

    class DocumentSide(models.TextChoices):
        FRONT        = "front",        _("Front")
        BACK         = "back",         _("Back")
        SINGLE       = "single",       _("Single Page")
        SELFIE       = "selfie",       _("Selfie")
        ADDRESS_PROOF = "address_proof", _("Address Proof")
    
    class Status(models.TextChoices):
        PENDING  = "pending",  _("Pending")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="kyc_documents"
    )

    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    document_side = models.CharField(max_length=20, choices=DocumentSide.choices)
    file = models.URLField(
        max_length=500,
        help_text=_("S3 key/URL of the uploaded document (stored after client completes presigned upload). "
                    "Accessed via signed URL only — never a public link."),
    )
   
    status        = models.CharField(
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
        verbose_name        = _("KYC document")
        verbose_name_plural = _("KYC documents")
        ordering            = ["-created_at"]

    def __str__(self):
        return f"KYC [{self.document_type}] — {self.user.email} ({self.status})"
