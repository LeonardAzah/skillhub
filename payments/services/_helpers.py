from decimal import Decimal

from accounts.models import User

from ..constants import PLATFORM_COMMISSION_RATE
from ..models import  Wallet, Transaction


def get_wallet(user_id: str) -> Wallet:
    """Row-locked fetch of a user's wallet. Must be called inside an atomic block."""
    return Wallet.objects.select_for_update().get(user_id=user_id)


def find_existing(appointment_id, transaction_type, account) -> Transaction | None:
    """
    The anchor/settlement leg for a given (appointment, operation) pair.
    Each caller passes its own fixed transaction_type/account — these are
    not meant to vary per call, only per calling function.
    """
    return (
        Transaction.objects
        .filter(
            appointment_id=appointment_id,
            transaction_type=transaction_type,
            account=account,
        )
        .first()
    )


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

def get_clearing_wallet() -> Wallet:
    """
    System wallet representing money in transit to/from external
    payment providers (Fapshi, Stripe). Every cash-in/cash-out posts
    an offsetting leg here so the ledger has no unexplained counterparty.
    """
    clearing_user, _ = User.objects.get_or_create(
        email="clearing@skillhub.internal",
        defaults={
            "username":          "clearing",
            "role":              "admin",
            "is_email_verified": True,
            "is_verified":       True,
        },
    )
    wallet, _ = Wallet.objects.get_or_create(user=clearing_user)
    return Wallet.objects.select_for_update().get(pk=wallet.pk)
