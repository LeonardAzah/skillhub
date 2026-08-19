
import logging
from datetime import timezone

from django.db import transaction as db_transaction

from utils.events import EventType
from notifications.publisher import publish_event

from ..models import Transaction, Wallet, Payment
from ..exceptions import CashOutServiceError

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
def process_cashin(payment: Payment) -> Transaction:
    """
    Finalize a successful cash-in.

    Responsibilities:
        - Lock the payment
        - Ensure it hasn't already been completed
        - Lock the wallet
        - Credit the wallet
        - Create the ledger transaction
        - Mark the payment as completed

    Safe to call multiple times.
    """
    existing_transaction = (
        Transaction.objects
        .filter(
            payment=payment,
            transaction_type=Transaction.Type.CASH_IN,
            status=Transaction.Status.COMPLETED,
        )
        .first()
    )

    if existing_transaction:
        logger.info("Duplicate cash-in ignored", extra={"key": payment.idempotency_key})
        return existing_transaction

    if payment.status == Payment.Status.COMPLETED:
        raise ValueError(
            "Payment is already completed but has no ledger transaction."
        )

    if payment.direction != Payment.Direction.CASH_IN:
        raise ValueError(
            "Payment is not a cash-in payment."
        )


    wallet = (
        Wallet.objects
        .select_for_update()
        .get(pk=payment.wallet.id)
    )

    if not wallet.is_active:
        raise ValueError(
            "Wallet is frozen. Contact support."
        )

    amount = payment.amount

    balance_before = wallet.balance

    wallet.balance += amount

    wallet.save(
        update_fields=[
            "balance",
            "updated_at",
        ]
    )

    txn = Transaction.objects.create(
       wallet=wallet,
        transaction_type=Transaction.Type.CASH_IN,
        amount=amount,
        balance_after=wallet.balance,
        payment=payment,
        appointment_id=payment.appointment_id,
        status=Transaction.Status.COMPLETED,
        reference=payment.provider_transaction_id,
        description=(
            f"Wallet top-up via {payment.provider}"
        ),
        metadata={
            "currency": payment.currency,
            "balance_before": str(balance_before),
            "balance_after": str(wallet.balance),
        },
    )

    payment.status = Payment.Status.COMPLETED
    payment.completed_at = timezone.now()

    payment.save(
        update_fields=[
            "status",
            "completed_at",
            "updated_at",
        ]
    )

    publish_event(
        EventType.WALLET_CREDITED,
        {
            "user_id": str(payment.user_id),
            "amount": str(amount),
            "currency": payment.currency,
            "transaction_id": str(txn.id),
            "new_balance": str(wallet.balance),
        },
    )

    return txn


@db_transaction.atomic
def process_failed_payment(
    payment: Payment,
    reason: str = "",
) -> Payment:
    """
    Mark a payment as failed.
    """
    if payment.status == Payment.Status.COMPLETED:
        return payment

    if payment.status == Payment.Status.FAILED:
        return payment

    payment.status = Payment.Status.FAILED
    payment.failure_reason = reason or "Payment failed."

    payment.save(
        update_fields=[
            "status",
            "failure_reason",
            "updated_at",
        ]
    )

    return payment


@db_transaction.atomic
def process_expired_payment(
    payment: Payment,
    reason: str = "",
) -> Payment:
    """
    Mark a payment as expired.
    """
    if payment.status == Payment.Status.COMPLETED:
        return payment

    if payment.status == Payment.Status.EXPIRED:
        return payment

    payment.status = Payment.Status.EXPIRED
    payment.failure_reason = reason or "Payment expired."

    payment.save(
        update_fields=[
            "status",
            "failure_reason",
            "updated_at",
        ]
    )

    return payment

@db_transaction.atomic
def complete_cash_out(payment):
    payment = (
        Payment.objects
        .select_for_update()
        .select_related("wallet")
        .get(pk=payment.pk)
    )

    # Idempotent webhook processing
    if payment.status == Payment.Status.COMPLETED:
        return payment

    wallet = (
        Wallet.objects
        .select_for_update()
        .get(pk=payment.wallet_id)
    )

    # Permanently debit the wallet
    wallet.balance -= payment.amount

    # Remove reservation
    wallet.reserved_balance -= payment.amount

    wallet.save(
        update_fields=[
            "balance",
            "reserved_balance",
            "updated_at",
        ]
    )

    # Create your finalized ledger entry here
    Transaction.objects.create(
        wallet=wallet,
        payment=payment,
        transaction_type=Transaction.EntryType.CASH_OUT,
        amount=-payment.amount,
        balance_after=wallet.balance,
        status=Transaction.Status.COMPLETED,
        reference=payment.provider_transaction_id,
                description=(
                    f"Wallet cashout via {payment.provider}"
                ),
                metadata={
                    "currency": payment.currency,
                    "balance_before": str(wallet.balance),
                    "balance_after": str(wallet.balance),
                },
    )

    payment.status = Payment.Status.COMPLETED
    payment.completed_at = timezone.now()

    payment.save(
        update_fields=[
            "status",
            "completed_at",
            "updated_at",
        ]
    )

    return payment


@db_transaction.atomic
def release_cashout_reservation(
    payment: Payment,
    *,
    status: str,
    reason: str,
) -> Payment:
    """
    Release reserved funds for a failed/expired cash-out.

    Idempotent and concurrency-safe.
    """

    if payment.direction != Payment.Direction.CASH_OUT:
        raise CashOutServiceError("Payment is not a cash-out.")

    # Already finalized
    if payment.status == Payment.Status.COMPLETED:
        return payment

    if payment.status == status:
        return payment

    wallet = (
        Wallet.objects
        .select_for_update()
        .get(pk=payment.wallet_id)
    )

    if wallet.reserved_balance < payment.amount:
        raise CashOutServiceError(
            "Reserved balance is lower than the payment amount."
        )

    wallet.reserved_balance -= payment.amount
    wallet.save(update_fields=["reserved_balance", "updated_at"])

    payment.status = status
    payment.failure_reason = reason
    payment.save(update_fields=["status", "failure_reason", "updated_at"])

    return payment


def process_cashout_failed(
    payment: Payment,
    reason: str = "",
) -> Payment:
    return release_cashout_reservation(
        payment,
        status=Payment.Status.FAILED,
        reason=reason or "Payout failed.",
    )


def process_cashout_expired(
    payment: Payment,
    reason: str = "",
) -> Payment:
    return release_cashout_reservation(
        payment,
        status=Payment.Status.EXPIRED,
        reason=reason or "Payout expired.",
    )