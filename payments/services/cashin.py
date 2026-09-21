import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction,IntegrityError

from ..providers.fapshi.client import FapshiClient
from ..models import Payment, WalletActivity
from ..exceptions import CashInProviderError

from ..providers.fapshi.exceptions import FapshiAPIError, FapshiError


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

    try:

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
    except IntegrityError:
        return Payment.objects.get(user=user, idempotency_key=idempotency_key)

    client = FapshiClient()

    try: 

        response = client.direct_pay(
            amount=int(amount),
            phone=payment.phone_number,
            email=user.email,
            method=payment.method,
            user_id=str(user.id),
            external_id=str(payment.id),
            message=f"Wallet top-up {payment.internal_reference}",
        )
    except ValueError as exc:
        payment.status = Payment.Status.FAILED
        payment.failure_reason = str(exc)
        payment.save(update_fields=["status", "failure_reason", "updated_at"])

        WalletActivity.objects.create(
        user=user, wallet=wallet, kind=WalletActivity.Kind.CASH_IN,
        status=WalletActivity.Status.FAILED, amount=amount, currency=currency,
        payment=payment, balance_after=wallet.balance,
        title="Wallet top-up failed", subtitle=str(exc),
    )
        raise CashInProviderError("Unable to initiate top-up.") from exc
    except FapshiAPIError as exc:
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            payment.status = Payment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])

            WalletActivity.objects.create(
            user=user, wallet=wallet, kind=WalletActivity.Kind.CASH_IN,
            status=WalletActivity.Status.FAILED, amount=amount, currency=currency,
            payment=payment, balance_after=wallet.balance,
            title="Wallet top-up failed", subtitle=str(exc),
        )
            raise CashInProviderError("Top-up was rejected by provider.") from exc
        raise CashInProviderError("Top-up is being confirmed with the provider.") from exc
    except FapshiError as exc:
        raise CashInProviderError("Top-up is being confirmed with the provider.")

    with transaction.atomic():
        payment.provider_transaction_id = response.get("transId")
        payment.status = Payment.Status.PENDING
        payment.metadata = {**payment.metadata, "fapshi_response": response}
        payment.save(update_fields=["provider_transaction_id", "status", "metadata", "updated_at"])

        wallet_activity = WalletActivity.objects.create(
            user=payment.user,
            wallet=payment.wallet,
            kind=WalletActivity.Kind.CASH_IN,
            status=WalletActivity.Status.PENDING,
            amount=payment.amount,
            currency=payment.currency,
            payment=payment,
            balance_after=payment.wallet.balance,
            title="Wallet cash-in pending",
            subtitle=f"via {payment.get_provider_display()}",
        )

    return payment