"""Escrow lifecycle: hold, release, and refund."""
from decimal import Decimal

from django.db import transaction as db_transaction

from appointments.models import Appointment
from utils.events import EventType
from notifications.publisher import publish_event

from ._helpers import calculate_fee, check_idempotency, get_platform_wallet, get_wallet
from ..constants import PLATFORM_COMMISSION_RATE
from ..models import EscrowAccount, Transaction, Wallet


@db_transaction.atomic
def hold_escrow(appointment_id: str, seeker_user_id: str, provider_user_id: str,
                amount: Decimal, idempotency_key: str) -> EscrowAccount:
    """
    Deduct amount from seeker balance → escrow_balance.
    Creates an EscrowAccount and a ESCROW_HOLD Transaction.
    Also stamps appointment.escrow_transaction_id.
    """
    existing = check_idempotency(idempotency_key)
    if existing:
        escrow = EscrowAccount.objects.get(appointment_id=appointment_id)
        return escrow

    seeker_wallet   = get_wallet(seeker_user_id)
    provider_wallet = Wallet.objects.select_for_update().get(user_id=provider_user_id)

    if not seeker_wallet.is_active:
        raise ValueError("Seeker wallet is frozen.")
    if seeker_wallet.balance < amount:
        raise ValueError(
            f"Insufficient balance. Available: {seeker_wallet.balance}, required: {amount}."
        )

    # Debit seeker available balance → escrow
    seeker_wallet.balance        -= amount
    seeker_wallet.escrow_balance += amount
    seeker_wallet.total_spent    += amount
    seeker_wallet.save(update_fields=["balance", "escrow_balance", "total_spent", "updated_at"])

    txn = Transaction.objects.create(
        wallet           = seeker_wallet,
        transaction_type = Transaction.Type.ESCROW_HOLD,
        amount           = -amount,       # debit from available
        status           = Transaction.Status.COMPLETED,
        idempotency_key  = idempotency_key,
        appointment_id   = appointment_id,
        description      = f"Escrow hold for appointment {appointment_id}",
    )

    escrow = EscrowAccount.objects.create(
        appointment_id  = appointment_id,
        seeker_wallet   = seeker_wallet,
        provider_wallet = provider_wallet,
        amount          = amount,
        platform_fee    = calculate_fee(amount),
        status          = EscrowAccount.Status.HELD,
        hold_transaction= txn,
    )

    # Stamp the appointment with the escrow transaction ID
    Appointment.objects.filter(id=appointment_id).update(
        escrow_transaction_id=txn.id
    )

    publish_event(EventType.ESCROW_HELD, {
        "appointment_id": str(appointment_id),
        "seeker_id":      str(seeker_user_id),
        "provider_id":    str(provider_user_id),
        "amount":         str(amount),
        "transaction_id": str(txn.id),
    })
    return escrow


@db_transaction.atomic
def release_escrow(appointment_id: str, idempotency_key: str) -> Transaction:
    """
    Release escrow to provider after CONFIRMED or AUTO_RELEASED.
    Deducts platform fee; credits provider wallet.
    """
    existing = check_idempotency(idempotency_key)
    if existing:
        return existing

    try:
        escrow = EscrowAccount.objects.select_for_update().get(appointment_id=appointment_id)
    except EscrowAccount.DoesNotExist:
        raise ValueError(f"No escrow found for appointment {appointment_id}.")

    if escrow.status != EscrowAccount.Status.HELD:
        raise ValueError(f"Escrow is in state '{escrow.status}', cannot release.")

    seeker_wallet   = Wallet.objects.select_for_update().get(id=escrow.seeker_wallet_id)
    provider_wallet = Wallet.objects.select_for_update().get(id=escrow.provider_wallet_id)

    net_amount = escrow.amount - escrow.platform_fee

    # Debit seeker escrow_balance
    seeker_wallet.escrow_balance -= escrow.amount
    seeker_wallet.save(update_fields=["escrow_balance", "updated_at"])

    # Credit provider
    provider_wallet.balance      += net_amount
    provider_wallet.total_earned += net_amount
    provider_wallet.save(update_fields=["balance", "total_earned", "updated_at"])

    # Release transaction
    release_txn = Transaction.objects.create(
        wallet           = provider_wallet,
        transaction_type = Transaction.Type.ESCROW_RELEASE,
        amount           = net_amount,
        status           = Transaction.Status.COMPLETED,
        idempotency_key  = idempotency_key,
        appointment_id   = appointment_id,
        description      = f"Escrow release for appointment {appointment_id}",
    )

    # Platform fee transaction
    if escrow.platform_fee > 0:
        platform_wallet = get_platform_wallet()
        platform_wallet.balance      += escrow.platform_fee
        platform_wallet.total_earned += escrow.platform_fee
        platform_wallet.save(update_fields=["balance", "total_earned", "updated_at"])
        Transaction.objects.create(
            wallet           = platform_wallet,
            transaction_type = Transaction.Type.PLATFORM_FEE,
            amount           = escrow.platform_fee,
            status           = Transaction.Status.COMPLETED,
            idempotency_key  = idempotency_key + ":fee",
            appointment_id   = appointment_id,
            description      = f"Platform commission {PLATFORM_COMMISSION_RATE*100:.1f}% for appointment {appointment_id}",
        )

    escrow.status               = EscrowAccount.Status.RELEASED
    escrow.release_transaction  = release_txn
    escrow.save(update_fields=["status", "release_transaction", "updated_at"])

    publish_event(EventType.ESCROW_RELEASED, {
        "appointment_id": str(appointment_id),
        "amount":         str(net_amount),
        "platform_fee":   str(escrow.platform_fee),
        "transaction_id": str(release_txn.id),
    })
    return release_txn


@db_transaction.atomic
def refund_escrow(appointment_id: str, idempotency_key: str,
                  partial_amount: Decimal | None = None) -> Transaction:
    """
    Refund escrow to seeker (REJECTED, EXPIRED, CANCELLED).
    partial_amount allows the split refund (late cancellation).
    """
    existing = check_idempotency(idempotency_key)
    if existing:
        return existing

    try:
        escrow = EscrowAccount.objects.select_for_update().get(appointment_id=appointment_id)
    except EscrowAccount.DoesNotExist:
        raise ValueError(f"No escrow found for appointment {appointment_id}.")

    if escrow.status != EscrowAccount.Status.HELD:
        raise ValueError(f"Escrow is in state '{escrow.status}', cannot refund.")

    refund_amount = partial_amount if partial_amount is not None else escrow.amount

    seeker_wallet = Wallet.objects.select_for_update().get(id=escrow.seeker_wallet_id)
    seeker_wallet.escrow_balance -= refund_amount
    seeker_wallet.balance        += refund_amount
    seeker_wallet.total_spent    = max(Decimal("0.00"), seeker_wallet.total_spent - refund_amount)
    seeker_wallet.save(update_fields=["balance", "escrow_balance", "total_spent", "updated_at"])

    # If partial refund, release remainder to provider
    if partial_amount and partial_amount < escrow.amount:
        provider_amount = escrow.amount - partial_amount
        provider_wallet = Wallet.objects.select_for_update().get(id=escrow.provider_wallet_id)
        provider_wallet.balance      += provider_amount
        provider_wallet.total_earned += provider_amount
        provider_wallet.save(update_fields=["balance", "total_earned", "updated_at"])
        Transaction.objects.create(
            wallet           = provider_wallet,
            transaction_type = Transaction.Type.ESCROW_RELEASE,
            amount           = provider_amount,
            balance_after = provider_wallet.balance,
            status           = Transaction.Status.COMPLETED,
            idempotency_key  = idempotency_key + ":partial_provider",
            appointment_id   = appointment_id,
            description      = "Partial cancellation compensation for provider",
        )
        remaining = escrow.amount - partial_amount
        seeker_wallet_locked = Wallet.objects.select_for_update().get(id=escrow.seeker_wallet_id)
        seeker_wallet_locked.escrow_balance -= remaining
        seeker_wallet_locked.save(update_fields=["escrow_balance", "updated_at"])

    refund_txn = Transaction.objects.create(
        wallet           = seeker_wallet,
        transaction_type = Transaction.Type.ESCROW_REFUND,
        amount           = refund_amount,
        balance_after = seeker_wallet.balance,
        status           = Transaction.Status.COMPLETED,
        idempotency_key  = idempotency_key,
        appointment_id   = appointment_id,
        description      = f"Escrow refund for appointment {appointment_id}",
    )

    escrow.status               = EscrowAccount.Status.REFUNDED
    escrow.release_transaction  = refund_txn
    escrow.save(update_fields=["status", "release_transaction", "updated_at"])

    publish_event(EventType.ESCROW_REFUNDED, {
        "appointment_id": str(appointment_id),
        "amount":         str(refund_amount),
        "transaction_id": str(refund_txn.id),
    })
    return refund_txn
