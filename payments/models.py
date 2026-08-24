from django.db import models

import hashlib
import os
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from utils.helpers import _setting


class WalletPin(models.Model):
    """
    A 4-digit PIN that authorises all financial actions:
      • booking confirmation (escrow hold)
      • withdrawal requests
      • any future high-value transaction

    Security design
    ───────────────
    • Stored as SHA-256(salt + PIN) — plaintext never persisted.
    • One PIN per user (OneToOne on User).
    • 5-attempt lockout for 15 minutes — matches account lockout policy.
    • Verification writes a short-lived Redis token consumed by the operation.

    Cache tokens written after successful verification
    ──────────────────────────────────────────────────
    • Booking:    wallet_pin_verified:{seeker_id}     TTL = 5 min
    • Withdrawal: wallet_pin_withdrawal:{user_id}     TTL = 5 min
    These keys are read (and consumed) by the relevant operation serializers.
    """

    MAX_ATTEMPTS    = 5
    LOCKOUT_MINUTES = 15

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="wallet_pin",
    )
    pin_hash         = models.CharField(max_length=128)
    salt             = models.CharField(max_length=64)
    failed_attempts  = models.PositiveSmallIntegerField(default=0)
    locked_until     = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("wallet PIN")

    @staticmethod
    def _hash(salt: str, pin: str) -> str:
        return hashlib.sha256(f"{salt}{pin}".encode()).hexdigest()

    @classmethod
    def create_or_update(cls, user, raw_pin: str) -> "WalletPin":
        salt     = os.urandom(24).hex()
        pin_hash = cls._hash(salt, raw_pin)
        obj, _   = cls.objects.update_or_create(
            user=user,
            defaults={
                "pin_hash":        pin_hash,
                "salt":            salt,
                "failed_attempts": 0,
                "locked_until":    None,
            },
        )
        return obj

    def verify(self, raw_pin: str) -> bool:
        """
        Verify raw PIN. Tracks failures and applies lockout.
        Returns True on success, False on failure.
        Raises ValueError if PIN is currently locked.
        """
        if self.is_locked:
            remaining = max(1, int((self.locked_until - timezone.now()).total_seconds() / 60))
            raise ValueError(
                f"Wallet PIN is locked after too many failed attempts. "
                f"Try again in {remaining} minute(s)."
            )
        if self._hash(self.salt, raw_pin) == self.pin_hash:
            if self.failed_attempts:
                self.failed_attempts = 0
                self.locked_until    = None
                self.save(update_fields=["failed_attempts", "locked_until", "updated_at"])
            return True

        self.failed_attempts += 1
        if self.failed_attempts >= self.MAX_ATTEMPTS:
            self.locked_until = timezone.now() + timedelta(minutes=self.LOCKOUT_MINUTES)
        self.save(update_fields=["failed_attempts", "locked_until", "updated_at"])
        return False

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and timezone.now() < self.locked_until)

    @property
    def is_set(self) -> bool:
        return bool(self.pin_hash)

    def __str__(self):
        return f"WalletPIN — {self.user.email}"


class Wallet(models.Model):
    """
    Every registered user gets a Wallet on account creation.
    wallet architecture.

    balance         — spendable, verified funds
    escrow_balance  — funds locked in active escrow (not spendable)
    total_earned    — lifetime earnings (providers)
    total_spent     — lifetime spend (seekers)
    currency        — ISO 4217 (XAF for Cameroon launch)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="wallet",
    )
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))

    reserved_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=_(
            "Funds reserved for pending operations such as cash-outs."
        ),
    )

    escrow_balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))

    total_earned = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))

    total_spent = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal("0.00"))

    currency = models.CharField(max_length=3, default="XAF")

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("wallet")
        indexes = [models.Index(fields=["user"])]

    def __str__(self):
        return f"Wallet({self.user.email}) {self.balance} {self.currency}"

    def has_funds(self, amount: Decimal) -> bool:
        return self.balance >= amount

    @property
    def total_balance(self) -> Decimal:
        """Available + escrowed funds."""
        return self.balance + self.escrow_balance

    def available_balance(self) -> Decimal:
        return self.balance - self.reserved_balance

class Payment(models.Model):
    """
    Represents an interaction with an external payment provider.
    A payment may or may not result in a wallet transaction.
    """

    class Provider(models.TextChoices):
        FAPSHI = "fapshi", _("Fapshi")
        STRIPE = "stripe", _("Stripe")

    class Method(models.TextChoices):
        MTN_MOBILE_MONEY = "mtn_mobile_money", "Mobile Money"
        ORANGE_MONEY = "orange_money", "Orange Money"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"

    class Direction(models.TextChoices):
        CASH_IN = "cash_in", _("Cash In")
        CASH_OUT = "cash_out", _("Cash Out")

    class Status(models.TextChoices):
        INITIATED = "initiated", _("Initiated")
        PENDING = "pending", _("Pending")
        PROCESSING = "processing", _("Processing")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")
        EXPIRED = "expired", _("Expired")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        _setting("AUTH_USER_MODEL", "accounts.User"),
        on_delete=models.PROTECT,
        related_name="payments",
    )

    wallet = models.ForeignKey(
        "Wallet",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
    )

    method = models.CharField(
        max_length=50,
        choices=Method.choices,
        null=True,
    blank=True,
    )

    direction = models.CharField(
        max_length=20,
        choices=Direction.choices,
    )

    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=3,
        default="XAF",
    )

    phone_number = models.CharField(
        max_length=20,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INITIATED,
        db_index=True,
    )
    appointment_id = models.UUIDField(
            null=True, blank=True, db_index=True,
            help_text=_("Linked appointment UUID if applicable."),
        )

    idempotency_key = models.CharField(
        max_length=255,
        db_index=True,
    )
    
    internal_reference = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
    )

    provider_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    provider_transaction_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    checkout_url = models.URLField(
        blank=True,
        default="",
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    failure_reason = models.TextField(
        blank=True,
        default="",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="payment_user_idempotency_unique",
            )
        ]

        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["provider"]),
            models.Index(fields=["internal_reference"]),
            models.Index(fields=["provider_reference"]),
        ]

    def __str__(self):
        return f"{self.internal_reference} ({self.status})"
    
class Transaction(models.Model):
    """
    Immutable double-entry ledger record.
    Every financial movement is a Transaction.
    The wallet balance is always derivable from the ledger.
    """

    class Type(models.TextChoices):
        CASH_IN         = "cash_in",        _("Cash In")
        CASH_OUT        = "cash_out",       _("Cash Out")
        ESCROW_HOLD     = "escrow_hold",    _("Escrow Hold")
        ESCROW_RELEASE  = "escrow_release", _("Escrow Release")
        ESCROW_REFUND   = "escrow_refund",  _("Escrow Refund")
        PLATFORM_FEE    = "platform_fee",   _("Platform Fee")
        WITHDRAWAL      = "withdrawal",     _("Withdrawal")
        REFUND          = "refund",         _("Refund")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    transaction_type = models.CharField(max_length=20, choices=Type.choices, db_index=True)
    amount = models.DecimalField(
        max_digits=15, decimal_places=2,
        help_text=_("Positive = credit, negative = debit."),
    )
    appointment_id = models.UUIDField(
                null=True, blank=True, db_index=True,
                help_text=_("Linked appointment UUID if applicable."),
            )

    balance_after = models.DecimalField(
    max_digits=15,
    decimal_places=2,
)

    payment = models.ForeignKey(
    Payment,
    null=True,
    blank=True,
    on_delete=models.PROTECT,
    related_name="ledger_entries",
)
    
    description = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("ledgerentry")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "transaction_type"]),
            models.Index(fields=["appointment_id"]),
        ]

    def __str__(self):
        return f"[{self.transaction_type}] {self.amount} {self.wallet.currency}"


class EscrowAccount(models.Model):
    """
    Per-appointment escrow record.
    Escrow lifecycle maps to appointment lifecycle.

    Status mirrors the appointment journey:
      HELD       → funds moved from seeker balance to escrow_balance
      RELEASED   → funds moved from escrow to provider (minus fee)
      REFUNDED   → funds returned to seeker
      DISPUTED   → frozen, pending admin resolution
    """

    class Status(models.TextChoices):
        HELD     = "held",     _("Held")
        RELEASED = "released", _("Released")
        REFUNDED = "refunded", _("Refunded")
        DISPUTED = "disputed", _("Disputed")

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment_id = models.UUIDField(unique=True, db_index=True)
    seeker_wallet  = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="escrows_as_seeker"
    )
    provider_wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="escrows_as_provider"
    )
    amount          = models.DecimalField(max_digits=15, decimal_places=2)
    platform_fee    = models.DecimalField(
        max_digits=15, decimal_places=2, default=Decimal("0.00"),
        help_text=_("Platform commission deducted on release."),
    )
    status          = models.CharField(max_length=10, choices=Status.choices,
                                       default=Status.HELD, db_index=True)
    hold_transaction    = models.ForeignKey(
        Transaction, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="escrow_hold",
    )
    release_transaction = models.ForeignKey(
        Transaction, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="escrow_release",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("escrow account")
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"Escrow[{self.appointment_id}] {self.amount} — {self.status}"


class PaymentGatewayLog(models.Model):
    """Audit trail for every webhook received from the payment gateway.idempotency + replay protection."""

    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gateway          = models.CharField(max_length=50, default="fapshi",
                                        help_text=_("Gateway name: fapshi, tangentopay, etc."))
    event_type       = models.CharField(max_length=100)
    raw_payload      = models.JSONField(default=dict)
    idempotency_key  = models.CharField(max_length=255, unique=True, db_index=True)
    transaction      = models.ForeignKey(
        Transaction, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="gateway_logs",
    )
    processed        = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True, default="")
    received_at      = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("payment gateway log")
        ordering = ["-received_at"]

    def __str__(self):
        return f"GatewayLog[{self.gateway}] {self.event_type} — {'ok' if self.processed else 'pending'}"
