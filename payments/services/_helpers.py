from decimal import Decimal

from accounts.models import User

from ..constants import PLATFORM_COMMISSION_RATE
from ..models import Transaction, Wallet


def get_wallet(user_id: str) -> Wallet:
    """Row-locked fetch of a user's wallet. Must be called inside an atomic block."""
    return Wallet.objects.select_for_update().get(user_id=user_id)


def check_idempotency(key: str) -> Transaction | None:
    return Transaction.objects.filter(idempotency_key=key, status=Transaction.Status.COMPLETED).first()


def calculate_fee(amount: Decimal) -> Decimal:
    return (amount * PLATFORM_COMMISSION_RATE).quantize(Decimal("0.01"))


def get_platform_wallet() -> Wallet:
    platform_user, _ = User.objects.get_or_create(
        email="platform@skillhub.internal",
        defaults={
            "username":          "platform",
            "role":              "admin",
            "is_email_verified": True,
            "is_verified":       True,
        },
    )
    wallet, _ = Wallet.objects.get_or_create(user=platform_user)
    return Wallet.objects.select_for_update().get(pk=wallet.pk)
