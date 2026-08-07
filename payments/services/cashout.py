import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from payments.models import Payment, Wallet

from .providers import initiate_provider_cash_out,release_cashout_reservation

class CashOutError(Exception):
    """Base exception for cash-out failures."""


class InsufficientFundsError(CashOutError):
    pass


class CashOutServiceError(CashOutError):
    pass


def initiate_cash_out(
    *,
    user,
    wallet: Wallet,
    amount,
    method,
    recipient_reference,
    recipient_name="",
    idempotency_key,
) -> Payment:
    """
    Create and initiate a cash-out payment.

    Responsibilities:
        1. Guarantee idempotency.
        2. Lock the wallet.
        3. Re-check available balance.
        4. Reserve the requested funds.
        5. Create the Payment record.
        6. Initiate the external provider payment.
        7. Update Payment with provider information.

    The wallet is NOT permanently debited here.

    Permanent debit + LedgerEntry creation happen when the
    provider confirms the cash-out through its webhook.
    """

    # ---------------------------------------------------------
    # 1. Fast idempotency lookup
    # ---------------------------------------------------------

    existing_payment = (
        Payment.objects
        .filter(
            user=user,
            idempotency_key=idempotency_key,
        )
        .first()
    )

    if existing_payment:
        return existing_payment

    # ---------------------------------------------------------
    # 2. Create payment + reserve funds atomically
    # ---------------------------------------------------------

    try:
        with transaction.atomic():

            # Always get the wallet again with a row lock.
            #
            # The wallet passed into the service may have been
            # loaded before another request changed it.
            wallet = (
                Wallet.objects
                .select_for_update()
                .get(
                    pk=wallet.pk,
                    user=user,
                    is_active=True,
                )
            )

            # -------------------------------------------------
            # Re-check balance under the lock
            # -------------------------------------------------

            if wallet.available_balance < amount:
                raise InsufficientFundsError(
                    f"Insufficient available balance. "
                    f"Available: {wallet.available_balance} "
                    f"{wallet.currency}."
                )

            # -------------------------------------------------
            # Generate internal reference
            # -------------------------------------------------

            internal_reference = (
                f"BOLO-{uuid.uuid4().hex[:12].upper()}"
            )

            # -------------------------------------------------
            # Reserve funds
            # -------------------------------------------------

            wallet.reserved_balance += amount

            wallet.save(
                update_fields=[
                    "reserved_balance",
                    "updated_at",
                ]
            )

            # -------------------------------------------------
            # Create Payment
            # -------------------------------------------------

            payment = Payment.objects.create(
                user=user,
                wallet=wallet,
                provider=method,
                direction=Payment.Direction.CASH_OUT,
                amount=amount,
                currency=wallet.currency,
                status=Payment.Status.INITIATED,
                idempotency_key=idempotency_key,
                internal_reference=internal_reference,
                metadata={
                    "recipient_reference": recipient_reference,
                    "recipient_name": recipient_name,
                },
            )

    except IntegrityError:
        # Another request may have created the same payment
        # concurrently using the same idempotency key.
        existing_payment = (
            Payment.objects
            .filter(
                user=user,
                idempotency_key=idempotency_key,
            )
            .first()
        )

        if existing_payment:
            return existing_payment

        raise

    # ---------------------------------------------------------
    # 3. Call external provider OUTSIDE database transaction
    # ---------------------------------------------------------

    try:
        provider_response = initiate_provider_cash_out(
            payment=payment,
            recipient_reference=recipient_reference,
        )

    except Exception as exc:
        # The provider call failed before the payout was
        # successfully initiated.
        release_cashout_reservation(
            payment_id=payment.id,
            reason=str(exc),
        )

        raise CashOutServiceError(
            "Unable to initiate cash-out with payment provider."
        ) from exc

    # ---------------------------------------------------------
    # 4. Update payment with provider information
    # ---------------------------------------------------------

    payment.status = Payment.Status.PENDING

    payment.provider_reference = (
        provider_response["provider_reference"]
    )

    payment.metadata = {
        **payment.metadata,
        "provider_response": provider_response,
    }

    payment.save(
        update_fields=[
            "status",
            "provider_reference",
            "metadata",
            "updated_at",
        ]
    )

    return payment