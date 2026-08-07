import uuid

from django.db import transaction

from ..models import Payment, Wallet


def initiate_provider_cash_out(
    *,
    payment,
    recipient_reference,
) -> dict:
    """
    Initiate the actual payout with Fapshi/TangentoPay/etc.

    This function should NOT modify your wallet or ledger.

    It should only communicate with the external provider and
    return the provider's result.
    """

    # Example:

    # response = fapshi_client.cashout(
    #     amount=payment.amount,
    #     currency=payment.currency,
    #     phone_number=recipient_reference,
    #     reference=payment.internal_reference,
    # )

    # return {
    #     "provider_reference": response.reference,
    # }

    return {
        "provider_reference": (
            f"MOCK-{uuid.uuid4().hex[:12].upper()}"
        ),
    }


def release_cashout_reservation(
    *,
    payment_id,
    reason="",
):
    """
    Release reserved funds when a cash-out cannot be initiated.
    """

    with transaction.atomic():

        payment = (
            Payment.objects
            .select_for_update()
            .select_related("wallet")
            .get(pk=payment_id)
        )

        # Don't release twice.
        if payment.status in {
            Payment.Status.FAILED,
            Payment.Status.CANCELLED,
        }:
            return

        wallet = (
            Wallet.objects
            .select_for_update()
            .get(pk=payment.wallet_id)
        )

        wallet.reserved_balance -= payment.amount

        wallet.save(
            update_fields=[
                "reserved_balance",
                "updated_at",
            ]
        )

        payment.status = Payment.Status.FAILED
        payment.failure_reason = reason
        payment.save(
            update_fields=[
                "status",
                "failure_reason",
                "updated_at",
            ]
        )