import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from ..providers.fapshi.client import FapshiClient
from ..models import Payment


def initiate_cash_in(
    *,
    user,
    wallet,
    amount: Decimal,
    currency: str,
    phone_number:str,
    medium: str,
    idempotency_key: str,
):
    """
    Create an internal Payment and initiate Fapshi checkout.
    The wallet is NOT credited here.
    Wallet credit happens after Fapshi confirms SUCCESSFUL.
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

        payment = Payment.objects.create(
            user=user,
            wallet=wallet,
            provider=Payment.Provider.FAPSHI,
            method=medium,
            direction=Payment.Direction.CASH_IN,
            amount=amount,
            phone_number=phone_number,
            currency=currency,
            status=Payment.Status.INITIATED,
            idempotency_key=idempotency_key,
            internal_reference=f"BOLO-{uuid.uuid4().hex[:12].upper()}",
        )

    client = FapshiClient()

    response = client.direct_pay(
        amount=int(amount),
        phone=payment.phone_number,
        email=user.email,
        medium=payment.method,
        user_id=str(user.id),
        external_id=str(payment.id),
        message=f"Wallet top-up {payment.internal_reference}",
    )

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