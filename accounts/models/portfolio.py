import uuid
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _

from ..constants import MAX_PORTFOLIO_ITEMS_PER_PROVIDER

ALLOWED_MEDIA_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif", "mp4", "mov")


def validate_media_url_extension(value):
    ext = value.rsplit(".", 1)[-1].lower().split("?")[0]  # strip query params before checking
    if ext not in ALLOWED_MEDIA_EXTENSIONS:
        raise ValidationError(
            _("Unsupported file type: .%(ext)s"), params={"ext": ext}
        )


class PortfolioItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        "ProviderProfile",
        on_delete=models.CASCADE,
        related_name="portfolio_items",
    )

    title = models.CharField(_("title"), max_length=200)
    description = models.TextField(_("description"), max_length=2000, blank=True, default="")
    category = models.CharField(_("category"), max_length=100, blank=True, default="")
    completed_on = models.DateField(_("completed on"), null=True, blank=True)
    client_name = models.CharField(
        _("client name"), max_length=200, blank=True, default="",
        help_text=_("Optional — only shown if provider chooses to display it."),
    )

    # Cover image lives on S3/Cloudinary — we only store the resulting URL
    cover_image_url = models.URLField(
        _("cover image URL"),
        max_length=1000,
        blank=True,
        default="",
        validators=[URLValidator(), validate_media_url_extension],
    )
    cover_image_public_id = models.CharField(
        _("cover image storage key"),
        max_length=500,
        blank=True,
        default="",
        help_text=_("Cloudinary public_id or S3 object key, used for deletion via SDK."),
    )

    is_featured = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("portfolio item")
        verbose_name_plural = _("portfolio items")
        ordering = ["display_order", "-completed_on", "-created_at"]
        indexes = [
            models.Index(fields=["provider", "is_published"]),
            models.Index(fields=["is_featured"]),
        ]

    def clean(self):
        super().clean()
        if self.provider_id and self._state.adding:
            existing_count = PortfolioItem.objects.filter(provider_id=self.provider_id).count()
            if existing_count >= MAX_PORTFOLIO_ITEMS_PER_PROVIDER:
                raise ValidationError(
                    {"provider": _(
                        "You have reached the maximum of %(max)d portfolio items."
                    ) % {"max": MAX_PORTFOLIO_ITEMS_PER_PROVIDER}}
                )

    def save(self, *args, skip_full_clean=False, **kwargs):
        if not skip_full_clean:
            self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.provider.user.email})"


class PortfolioImage(models.Model):
    """
    Additional gallery images/videos, each hosted externally (S3/Cloudinary).
    """

    MEDIA_IMAGE = "image"
    MEDIA_VIDEO = "video"
    MEDIA_TYPE_CHOICES = [
        (MEDIA_IMAGE, _("Image")),
        (MEDIA_VIDEO, _("Video")),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio_item = models.ForeignKey(
        PortfolioItem,
        on_delete=models.CASCADE,
        related_name="images",
    )

    url = models.URLField(
        _("media URL"),
        max_length=1000,
        validators=[URLValidator(), validate_media_url_extension],
    )
    public_id = models.CharField(
        _("storage key"),
        max_length=500,
        blank=True,
        default="",
        help_text=_("Cloudinary public_id or S3 object key, used for deletion via SDK."),
    )
    media_type = models.CharField(
        max_length=10, choices=MEDIA_TYPE_CHOICES, default=MEDIA_IMAGE
    )
    thumbnail_url = models.URLField(
        _("thumbnail URL"), max_length=1000, blank=True, default="",
        help_text=_("Optional — e.g. video poster frame or resized preview."),
    )
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)

    caption = models.CharField(_("caption"), max_length=200, blank=True, default="")
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("portfolio image")
        verbose_name_plural = _("portfolio images")
        ordering = ["display_order", "created_at"]

    def __str__(self):
        return f"{self.media_type} for {self.portfolio_item.title}"