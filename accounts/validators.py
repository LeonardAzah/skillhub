import re
from rest_framework import serializers

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.conf import settings


from .models import User 

class PasswordComplexityValidator:
    """
    Enforces: at least 1 uppercase letter, 1 digit, and 1 special character.
    Works alongside Django's built-in MinimumLengthValidator.
    """
    SPECIAL_CHARS = r"[!@#$%^&*(),.?\":{}|<>_\-\+=\[\]\\\/;'`~]"

    def validate(self, password, user=None):
        errors = []
        if not re.search(r"[A-Z]", password):
            errors.append(_("Password must contain at least one uppercase letter."))
        if not re.search(r"\d", password):
            errors.append(_("Password must contain at least one digit."))
        if not re.search(self.SPECIAL_CHARS, password):
            errors.append(_("Password must contain at least one special character."))
        if errors:
            raise ValidationError(errors)
    
    def get_help_text(self):
        return _(
            "Your password must contain at least one uppercase letter, "
            "one digit, and one special character."
        )

def validate_kyc_file(value):
    """Validate KYC upload: type and size."""

    allowed_types = getattr(
        settings, "KYC_ALLOWED_FILE_TYPES", ["image/jpeg", "image/png", "application/pdf"]
    )
    max_mb = getattr(settings, "KYC_MAX_FILE_SIZE_MB", 20)

    # Check content type
    content_type = getattr(value, "content_type", None)
    if content_type and content_type not in allowed_types:
        raise ValidationError(
            _("Unsupported file type. Please upload a JPEG, PNG, or PDF."),
            code="invalid_file_type",
        )

    # Check size
    if hasattr(value, "size") and value.size > max_mb * 1024 * 1024:
        raise ValidationError(
            _("File too large. Maximum allowed size is %(max_mb)s MB."),
            code="file_too_large",
            params={"max_mb": max_mb},
        )
    