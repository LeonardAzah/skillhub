import uuid

from django.db import transaction

from payments.providers.fapshi.client import FapshiClient
from payments.models import Payment, Wallet

from ..exceptions import CashOutProviderError, InsufficientFundsError

from .wallet import release_cashout_reservation

def initiate_cash_out(
    *,
    user,
    wallet,
    amount,
    method,
    recipient_reference,
    recipient_name="",
    idempotency_key,
):
    """
    Create an internal Payment and initiate Fapshi checkout.
    Reserve wallet funds and initiate a Fapshi payout.
    """

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

    with transaction.atomic():

        wallet = (
            Wallet.objects
            .select_for_update()
            .get(
                pk=wallet.pk,
                user=user,
                is_active=True,
            )
        )

        # IMPORTANT: authoritative balance check
        if wallet.available_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient available balance. "
                f"Available: {wallet.available_balance} "
                f"{wallet.currency}."
            )

        payment = Payment.objects.create(
            user=user,
            wallet=wallet,
            provider=Payment.Provider.FAPSHI,
            method=method,
            direction=Payment.Direction.CASH_OUT,
            amount=amount,
            currency=wallet.currency,
            status=Payment.Status.INITIATED,
            idempotency_key=idempotency_key,
            phone_number=recipient_reference,
            internal_reference=(
                f"BOLO-{uuid.uuid4().hex[:12].upper()}"
            ),
            metadata={
                "recipient_reference": recipient_reference,
                "recipient_name": recipient_name,
            },
        )

        # Reserve funds
        wallet.reserved_balance += amount

        wallet.save(
            update_fields=[
                "reserved_balance",
                "updated_at",
            ]
        )

    try:
        client = FapshiClient()

        response = client.payout(
            amount=int(amount),
            phone=recipient_reference,
            name=recipient_name or None,
            email=user.email,
            user_id=str(user.id),
            external_id=str(payment.id),
            medium="mobile_money",
            message=(
                f"Wallet withdrawal "
                f"{payment.internal_reference}"
            ),
        )

    except Exception as exc:
        release_cashout_reservation(
                payment=payment, 
                status=Payment.Status.FAILED,
                reason="Unable to initiate cashout with fapshi."
            )
        
        raise CashOutProviderError(
            "Unable to initiate payout."
        ) from exc


    payment.provider_reference = response.get("transId")

    payment.status = Payment.Status.PENDING

    payment.metadata = {
        **payment.metadata,
        "fapshi_response": response,
    }

    payment.save(
        update_fields=[
            "provider_reference",
            "status",
            "metadata",
            "updated_at",
        ]
    )

    return payment