import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import PaymentGatewayLog, Payment
from ..services import process_cashin, process_expired_payment, process_failed_payment, complete_cash_out, process_cashout_expired, process_cashout_failed

from ..providers.fapshi.client import FapshiClient

from utils.exceptions import error_response


logger = logging.getLogger(__name__)

class PaymentWebhookView(APIView):
    """
    POST /api/v1/payments/webhook/

    Fapshi webhook endpoint.

    The webhook is unauthenticated because it is called by Fapshi.
    The transaction status is verified directly with Fapshi before
    changing any wallet state.
    """

    permission_classes = [AllowAny]

    def post(self, request):

        payload = request.data
        trans_id = payload.get("transId")

        if not trans_id:
            return error_response(message="transId is required.", status_code=status.HTTP_400_BAD_REQUEST)
            
        client = FapshiClient()

        try:
            event = client.payment_status(trans_id)

        except Exception as exc:
            logger.exception(
                "Failed to verify Fapshi transaction",
                extra={
                    "trans_id": trans_id,
                    "error": str(exc),
                },
            )

            return error_response(
                message="Unable to verify transaction.",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
       
        try:
            payment = Payment.objects.get(
                provider_transaction_id=trans_id,
                provider=Payment.Provider.FAPSHI,
            )

        except Payment.DoesNotExist:

            logger.warning(
                "Fapshi transaction does not belong to our system",
                extra={
                    "trans_id": trans_id,
                },
            )

            return error_response(
                message="Unknown transaction.",
                status_code=status.HTTP_404_NOT_FOUND
            )

        log, created = PaymentGatewayLog.objects.get_or_create(
            gateway="fapshi",
            provider_transaction_id=trans_id,
            defaults={
                "event_type": "payment.status",
                "raw_payload": payload,
            },
        )

        if not created and log.processed:
            logger.info(
                "Duplicate Fapshi webhook ignored",
                extra={
                    "trans_id": trans_id,
                },
            )

            return Response(
                {
                    "status": "ok",
                    "duplicate": True,
                },
                status=status.HTTP_200_OK,
            )

        try:

            if event["status"] == "SUCCESSFUL":
                if payment.direction == payment.Direction.CASH_IN:
                    txn = process_cashin(
                        payment=payment,
                    )

                elif payment.direction == payment.Direction.CASH_OUT:
                    txn = complete_cash_out(
                        payment=payment
                    )

                log.transaction = txn
                log.processed = True
                log.save(
                    update_fields=[
                        "transaction",
                        "processed",
                    ]
                )

            elif event["status"] == "FAILED":
                if payment.direction == payment.Direction.CASH_IN:
                    process_failed_payment(
                        payment=payment,
                        reason=event.get(
                        "message",
                        "Fapshi payment failed.",
                            ),
                    )
                elif payment.direction == payment.Direction.CASH_OUT:
                    process_cashout_failed(
                        payment=payment,
                        reason=event.get("message", "Fapshi cash-out failed."),
                    )

                log.processed = True
                log.save(
                    update_fields=[
                        "processed",
                    ]
                )

            elif event["status"] == "EXPIRED":
                if payment.direction == payment.Direction.CASH_IN:
                    process_expired_payment(
                        payment=payment,
                        reason=event.get(
                                "message",
                                "Fapshi payment expired.",
                        ),
                    )

                elif payment.direction == payment.Direction.CASH_OUT:
                    process_expired_payment(
                        payment=payment,
                        reason=event.get("message", "Fapshi cash-out expired."),
                    )

                log.processed = True
                log.save(
                    update_fields=[
                        "processed",
                    ]
                )

            else:

                logger.info(
                    "Unhandled Fapshi status",
                    extra={
                        "trans_id": trans_id,
                        "status": event.get("status"),
                    },
                )

        except Exception as exc:

            log.processing_error = str(exc)

            log.save(
                update_fields=[
                    "processing_error",
                ]
            )

            logger.exception(
                "Fapshi webhook processing failed",
                extra={
                    "trans_id": trans_id,
                },
            )

            return error_response(
                message="Processing failed.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "status": "ok",
            },
            status=status.HTTP_200_OK,
        )