
import logging
from decimal import Decimal

from django.db import transaction as db_transaction

from utils.events import EventType
from notifications.publisher import publish_event

from ._helpers import check_idempotency, get_wallet
from ..models import Transaction, Wallet

logger = logging.getLogger(__name__)


@db_transaction.atomic
def create_wallet(user) -> Wallet:
    """
    Create a wallet for a new user.
    Called from accounts app post-registration signal or directly.
    """
    wallet, created = Wallet.objects.get_or_create(user=user)
    return wallet


@db_transaction.atomic
def process_cashin(user_id, amount, gateway_reference: str,
                   idempotency_key: str, currency: str = "XAF") -> Transaction:
    """
    SRS §9.4 — Credit the wallet after a successful gateway payment.
    Idempotent: returns existing transaction if key already processed.
    """
    amount = Decimal(str(amount))
    user_id = str(user_id)
    existing = check_idempotency(idempotency_key)
    if existing:
        logger.info("Duplicate cash-in ignored", extra={"key": idempotency_key})
        return existing

    wallet = get_wallet(user_id)

    if not wallet.is_active:
        raise ValueError("Wallet is frozen. Contact support.")

    wallet.balance += amount
    wallet.save(update_fields=["balance", "updated_at"])

    txn = Transaction.objects.create(
        wallet           = wallet,
        transaction_type = Transaction.Type.CASH_IN,
        amount           = amount,
        status           = Transaction.Status.COMPLETED,
        idempotency_key  = idempotency_key,
        reference        = gateway_reference,
        description      = f"Wallet top-up via payment gateway ({currency})",
        metadata         = {"currency": currency},
    )

    publish_event(EventType.WALLET_CREDITED, {
        "user_id":        str(user_id),
        "amount":         str(amount),
        "currency":       currency,
        "transaction_id": str(txn.id),
        "new_balance":    str(wallet.balance),
    })
    return txn
