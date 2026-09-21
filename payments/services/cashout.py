import uuid

from django.db import transaction

from payments.providers.fapshi.client import FapshiClient
from payments.models import Payment, WalletActivity, Wallet

from ..exceptions import CashOutProviderError, InsufficientFundsError, InvalidPaymentStateError

from .wallet import release_cashout_reservation
from ..providers.fapshi.exceptions import FapshiAPIError,  FapshiError

def initiate_cash_out(
    payment
):
    """
    Create an internal Payment and initiate Fapshi checkout.
    Reserve wallet funds and initiate a Fapshi payout.
    """

    with transaction.atomic():

        updated = Payment.objects.filter(
            id=payment.id, status=Payment.Status.INITIATED
        ).update(status=Payment.Status.PROCESSING)

        if not updated:
            raise InvalidPaymentStateError("Payment is no longer awaiting confirmation.")

        wallet = Wallet.objects.select_for_update().get(pk=payment.wallet.id)

        # IMPORTANT: authoritative balance check
        if wallet.available_balance < payment.amount:
            payment.status = Payment.Status.INITIATED
            payment.save(update_fields=["status", "updated_at"])
            raise InsufficientFundsError(
                f"Insufficient available balance. "
                f"Available: {wallet.available_balance} "
                f"{wallet.currency}."
            )

        # Reserve funds
        wallet.reserved_balance += payment.amount

        wallet.save(
            update_fields=[
                "reserved_balance",
                "updated_at",
            ]
        )

    payment.refresh_from_db()

    try:
        client = FapshiClient()

        response = client.payout(
            amount=int(payment.amount),
            phone=payment.phone_number,
            name=payment.metadata.get("recipient_name") or None,
            email=payment.user.email,
            user_id=str(payment.user.id),
            external_id=str(payment.id),
            medium=payment.method,
            message=(
                f"Wallet withdrawal "
                f"{payment.internal_reference}"
            ),
        )

    except ValueError as exc:
        release_cashout_reservation(
                payment=payment, 
                status=Payment.Status.FAILED,
                reason="Unable to initiate cashout with fapshi."
            )

        WalletActivity.objects.create(
                user=payment.user, 
                wallet=wallet, 
                kind=WalletActivity.Kind.CASH_OUT,
                status=WalletActivity.Status.FAILED, amount=payment.amount, 
                currency=payment.currency,
                payment=payment, 
                balance_after=wallet.balance,
                title="Wallet cash-out failed", subtitle=str(exc),
            )
        
        raise CashOutProviderError(
            "Unable to initiate payout."
        ) from exc
    except FapshiAPIError as exc:
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            # Fapshi received and definitively rejected the request.
            release_cashout_reservation(
                payment=payment,
                status=Payment.Status.FAILED,
                reason=str(exc),
            )

            WalletActivity.objects.create(
                        user=payment.user, 
                        wallet=wallet, 
                        kind=WalletActivity.Kind.CASH_OUT,
                        status=WalletActivity.Status.FAILED, amount=payment.amount, 
                        currency=payment.currency,
                        payment=payment, 
                        balance_after=wallet.balance,
                        title="Wallet cash-out failed", 
                        subtitle=str(exc),
                    )
            
            raise CashOutProviderError("Payout was rejected by provider.") from exc

        # 5xx / unknown status — Fapshi's own side errored, outcome unclear.
        payment.status = Payment.Status.PROCESSING
        payment.metadata = {**payment.metadata, "provider_error": str(exc)}
        payment.save(update_fields=["status", "metadata", "updated_at"])
        raise CashOutProviderError("Payout is being confirmed with the provider.") from exc

    except FapshiError as exc:
        # Transport failure (timeout, connection drop) — we don't know if
        # Fapshi received it. Do NOT release the reservation.
        payment.status = Payment.Status.PROCESSING
        payment.metadata = {**payment.metadata, "provider_error": str(exc)}
        payment.save(update_fields=["status", "metadata", "updated_at"])
        raise CashOutProviderError("Payout is being confirmed with the provider.") from exc

    with transaction.atomic():

        wallet = Wallet.objects.select_for_update().get(pk=payment.wallet.id)
        payment.provider_transaction_id = response.get("transId")
        payment.status = Payment.Status.PENDING
        payment.metadata = {**payment.metadata, "fapshi_response": response}
        payment.save(update_fields=["provider_transaction_id", "status", "metadata", "updated_at"])

        WalletActivity.objects.create(
            user=payment.user,
            wallet=payment.wallet,
            kind=WalletActivity.Kind.CASH_OUT,
            amount=payment.amount,
            status=WalletActivity.Status.PENDING,
            currency=payment.currency,
            balance_after=payment.wallet.balance,
            title="Wallet cash-out pending",
            subtitle=f"via {payment.get_provider_display()}",
            payment=payment,
        )

    return payment