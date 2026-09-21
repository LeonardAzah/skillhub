import re
import uuid
from decimal import Decimal

from django.core.cache import cache
from rest_framework import serializers

from appointments.models import Appointment


from .constants import (
    MIN_WITHDRAWAL_AMOUNT,
    WALLET_PIN_TTL_BOOKING,
    WALLET_PIN_TTL_WITHDRAWAL,
    WALLET_PIN_TOKEN_BOOKING,
    WALLET_PIN_TOKEN_WITHDRAWAL,
)
from .models import EscrowAccount, Transaction, Wallet, WalletPin, Payment, WalletActivity

from utils.serializers import WalletPinSerializer

PIN_RE = re.compile(r"^\d{4}$")

MIN_CASHIN_AMOUNT = Decimal("500.00")



def _validate_pin_format(value: str) -> str:
    if not PIN_RE.match(str(value)):
        raise serializers.ValidationError("PIN must be exactly 4 digits (0–9).")
    return str(value)


class SetWalletPinSerializer(serializers.Serializer):
    """    
    Set or change the wallet PIN.
    First time: new_pin + confirm_pin only.
    Change:     current_pin + new_pin + confirm_pin.
    """
    current_pin = serializers.CharField(
        required=False, write_only=True,
        help_text="Required only when changing an existing PIN."
    )
    new_pin     = serializers.CharField(write_only=True)
    confirm_pin = serializers.CharField(write_only=True)

    def validate_new_pin(self, v):     return _validate_pin_format(v)
    def validate_confirm_pin(self, v): return _validate_pin_format(v)

    def validate(self, attrs):
        user = self.context["request"].user
        new_pin     = attrs["new_pin"]
        confirm_pin = attrs["confirm_pin"]

        if new_pin != confirm_pin:
            raise serializers.ValidationError({"confirm_pin": "PINs do not match."})

        # Changing an existing PIN requires the current one
        if hasattr(user, "wallet_pin") and user.wallet_pin.is_set:
            current = attrs.get("current_pin")
            if not current:
                raise serializers.ValidationError(
                    {"current_pin": "Current PIN is required when changing an existing PIN."}
                )
            try:
                ok = user.wallet_pin.verify(current)
            except ValueError as e:
                raise serializers.ValidationError({"current_pin": str(e)})
            if not ok:
                raise serializers.ValidationError({"current_pin": "Incorrect current PIN."})

        return attrs

    def save(self) -> WalletPin:
        user = self.context["request"].user
        return WalletPin.create_or_update(user, self.validated_data["new_pin"])


class WalletPinStatusSerializer(serializers.Serializer):
    """Read-only PIN status (no secrets exposed)."""
    is_set        = serializers.BooleanField()
    is_locked     = serializers.BooleanField()
    locked_until  = serializers.DateTimeField(allow_null=True)
    booking_token_active    = serializers.BooleanField()
    withdrawal_token_active = serializers.BooleanField()


class WalletSerializer(serializers.ModelSerializer):
    """Own wallet balance."""
    class Meta:
        model  = Wallet
        fields = [
            "id", "balance", "escrow_balance", "total_balance",
            "total_earned", "total_spent", "currency", "is_active",
            "created_at",
        ]
        read_only_fields = fields


class CashInInitiateSerializer(serializers.Serializer):
    
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
        min_value=MIN_CASHIN_AMOUNT,
    )

    currency = serializers.ChoiceField(
        choices=["XAF"],
        default="XAF",
    )

    phone_number = serializers.CharField(
        max_length=20,
        trim_whitespace=True,
    )

    method = serializers.ChoiceField(
        choices=Payment.Method.choices,
    )

    idempotency_key = serializers.UUIDField(
        default=uuid.uuid4,
        help_text="Unique key used to safely retry the request.",
    )

    def validate_phone_number(self, value):
        value = value.strip()

        if not re.fullmatch(r"6\d{8}", value):
            raise serializers.ValidationError(
                "Phone number must contain exactly 9 digits "
                "and start with 6, e.g. 612345678."
            )

        return value

    def validate_amount(self, value):
        """
        Validate minimum cash-in amount.
        """

        if value < MIN_CASHIN_AMOUNT:
            raise serializers.ValidationError(
                f"Minimum cash-in amount is "
                f"{MIN_CASHIN_AMOUNT} XAF."
            )

        return value

    def validate_currency(self, value):
        """
        Normalize currency.
        """
        return value.upper()

    def validate(self, attrs):
        """
        Cross-field/business validation.
        """

        wallet = self.context.get("wallet")

        if wallet is None:
            raise serializers.ValidationError(
                "Wallet is required."
            )

        if not wallet.is_active:
            raise serializers.ValidationError(
                "Your wallet is currently inactive."
            )

        method = attrs["method"]

        if method == Payment.Method.BANK_TRANSFER:
            raise serializers.ValidationError(
                {
                    "method": (
                        "Bank transfer is not currently "
                        "supported for wallet cash-in."
                    )
                }
            )

        if attrs["currency"] != wallet.currency:
            raise serializers.ValidationError(
                {
                    "currency": (
                        f"Wallet currency is {wallet.currency}."
                    )
                }
            )


        if method not in {
            Payment.Method.MTN_MOBILE_MONEY,
            Payment.Method.ORANGE_MONEY,
        }:
            raise serializers.ValidationError(
                {
                    "method": "Unsupported cash-in method."
                }
            )

        return attrs


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Transaction
        fields = "__all__"
        def get_fields(self):
            fields = super().get_fields()
            for field in fields.values():
                field.read_only = True
            return fields

class WalletActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletActivity
        fields = "__all__"

        def get_fields(Self):
            fields = super().get_fields()
            for field in fields.values():
                field.read_only = True
            return fields

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Payment
        fields = "__all__"

        def get_fields(self):
            fields = super().get_fields()
            for field in fields.values():
                field.read_only = True
            return fields

class CashOutSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=15,
        decimal_places=2,
    )

    currency = serializers.CharField(
        max_length=3,
        default="XAF",
    )

    provider = serializers.ChoiceField(
        choices=Payment.Provider.choices,
        required=False,
    )

    method = serializers.ChoiceField(
        choices=Payment.Method.choices,
    )

    phone_number = serializers.CharField(
        max_length=12,
    )

    def validate_amount(self, value):
        if value < MIN_WITHDRAWAL_AMOUNT:
            raise serializers.ValidationError(
                f"Minimum withdrawal amount is "
                f"{MIN_WITHDRAWAL_AMOUNT} XAF."
            )

        return value


    def validate(self, attrs):
        request = self.context["request"]
        wallet = self.context["wallet"]

        # Idempotency key

        idempotency_key = self.context.get("idempotency_key")

        if not idempotency_key:
            raise serializers.ValidationError(
                {
                    "idempotency_key": (
                        "Idempotency-Key header is required."
                    )
                }
            )

        # Wallet

        if not wallet.is_active:
            raise serializers.ValidationError(
                {"wallet": "Wallet is inactive."}
            )

        # Currency

        if wallet.currency != "XAF":
            raise serializers.ValidationError(
                {
                    "currency": (
                        f"Withdrawals are only supported for "
                        f"{wallet.currency} wallets."
                    )
                }
            )

        # Balance

        amount = attrs["amount"]

        if wallet.available_balance < amount:
            raise serializers.ValidationError(
                {
                    "amount": (
                        "Insufficient available balance. "
                        f"Available: {wallet.available_balance} XAF."
                    )
                }
            )

        user = request.user


        # Disputes

        has_dispute = (
            Appointment.objects.filter(
                customer=user,
                status=Appointment.Status.DISPUTED,
            ).exists()
            or
            Appointment.objects.filter(
                provider__user=user,
                status=Appointment.Status.DISPUTED,
            ).exists()
        )

        if has_dispute:
            raise serializers.ValidationError(
                "Withdrawals are blocked while you have "
                "an active dispute."
            )

        return attrs


class PinCashoutConfirmationSerializer(WalletPinSerializer):

    def validate(self, attrs):
        payment = self.context["payment"]

        if payment.status != Payment.Status.INITIATED:
            raise serializers.ValidationError(
                f"This payout is in '{payment.status}' status "
                "and does not require PIN confirmation."
            )

        try:
            from payments.services.pin import verify_wallet_pin
            verify_wallet_pin(
                self.context["request"].user,
                attrs["pin"],
            )
        except ValueError as exc:
            raise serializers.ValidationError({"pin": str(exc)})

        return attrs
    

class EscrowSerializer(serializers.ModelSerializer):
    class Meta:
        model  = EscrowAccount
        fields = [
            "id", "appointment_id", "amount", "platform_fee",
            "status", "created_at", "updated_at",
        ]
        read_only_fields = fields


class TransactionListSerializer(serializers.ModelSerializer):
    wallet_owner = serializers.CharField(source='wallet.user.username', read_only=True)

    class Meta:
        model = Transaction
        fields = "__all__"

class PaymentListSerializer(serializers.ModelSerializer):
    user = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = Payment
        fields = "__all__"