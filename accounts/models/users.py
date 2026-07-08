from django.db import models
from datetime import timedelta
from django.utils import timezone

import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

from django.utils.translation import gettext_lazy as _
from django.conf import settings



class UserManager(BaseUserManager):
    """Custom manager for the User model."""
    def create_user(self, email, username, password=None, **extra_fields):
        """Create and save a User with the given email, username, and password."""
        if not email:
            raise ValueError('Email is required.')
        if not username:
            raise ValueError("Username is required.")

        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        user = self.model(email=email, username=username, **extra_fields)
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_supperuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "admin")
        extra_fields.setdefault("is_email_verified", True)
        return self.create_user(email, username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """ 
    Central auth user model.
    Support email/password + google OAuth, RBAC roles.
    """

    class Role(models.TextChoices):
        SEEKER   = "seeker",   _("Service Seeker")
        PROVIDER = "provider", _("Service Provider")
        ADMIN    = "admin",    _("Platform Administrator")

    class AccountType(models.TextChoices):
        SEEKER   = "seeker",   _("Service Seeker")
        PROVIDER = "provider", _("Service Provider")
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_("email address"), unique=True, db_index=True)
    username = models.CharField(
        _("username"),
        max_length=50,
        unique=True,
        help_text=_("Alphanumeric, max 50 chars."),
    )

    phone_number = models.CharField(
        _("phone number"),
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text=_("E.164 format, e.g. +237123456789"),
    )

    profile_picture = models.URLField(
        max_length=500, blank=True, default="",
        help_text=_("CloudFront URL of the S3-stored/cloudinary profile image (set after presigned upload)."),
    )

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        null=True,
        blank=True,
        help_text=_("Assigned after onboarding selection."),
    )

    account_type = models.CharField(
        max_length=10,
        choices=AccountType.choices,
        null=True,
        blank=True,
        help_text=_("Set during onboarding. Nullable until selected."),
    )

    is_email_verified = models.BooleanField(
        _("email verified"),
        default=False,
        help_text=_("True after user clicks verification link."),
    )

    is_verified = models.BooleanField(
        _("KYC verified"),
        default=False,
        help_text=_("True after admin approves KYC documents."),
    )

    google_uid = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text=_("Google OAuth UID for linked accounts."),
    )
    auth_provider = models.CharField(
        max_length=20,
        default="email",
        choices=[("email", "Email/Password"), ("google", "Google OAuth")],
    )

    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)

    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    lockout_until         = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        verbose_name        = _("user")
        verbose_name_plural = _("users")
        ordering            = ["-created_at"]

    def __str__(self):
        return f"{self.email} ({self.role or 'unset'})"

    # ── Lockout helpers

    @property
    def is_locked_out(self) -> bool:
        """30-minute lockout after 5 failed logins."""
        return bool(self.lockout_until and timezone.now() < self.lockout_until)

    def record_failed_login(self) -> None:
        """
        Increment counter; lock account after threshold.
        Emits accounts.user.account_locked when the threshold is crossed.
        """
        self.failed_login_attempts += 1
        threshold   = getattr(settings, "ACCOUNT_LOCKOUT_ATTEMPTS", 5)
        duration    = getattr(settings, "ACCOUNT_LOCKOUT_DURATION", 30)
        just_locked = False

        if self.failed_login_attempts >= threshold and not self.lockout_until:
            self.lockout_until = timezone.now() + timedelta(minutes=duration)
            just_locked = True

        self.save(update_fields=["failed_login_attempts", "lockout_until"])

        if just_locked:
            pass

    def clear_failed_logins(self) -> None:
        """Reset counter on successful login."""
        if self.failed_login_attempts > 0 or self.lockout_until:
            self.failed_login_attempts = 0
            self.lockout_until         = None
            self.save(update_fields=["failed_login_attempts", "lockout_until"])

    @property
    def has_completed_onboarding(self) -> bool:
        return self.account_type is not None








