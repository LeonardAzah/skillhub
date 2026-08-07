"""
BoloConnect — apps/payments/views/webhook.py
SRS §9.4 — Payment gateway webhook

Endpoints
─────────
POST   /api/v1/payments/webhook/
"""
import hashlib
import hmac
import logging
import uuid

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import PaymentGatewayLog
from ..services import process_cashin

logger = logging.getLogger(__name__)


class PaymentWebhookView(APIView):
    """
    POST /api/v1/payments/webhook/
    SRS §9.4 — Receives gateway callback after user completes payment.
    HMAC signature verified; idempotency enforced.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        # ── HMAC verification ─────────────────────────────────────────────
        webhook_secret = getattr(settings, "PAYMENT_WEBHOOK_SECRET", "")
        if webhook_secret:
            received_sig = request.headers.get("X-Webhook-Signature", "")
            expected_sig = hmac.new(
                webhook_secret.encode(),
                request.body,
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(received_sig, expected_sig):
                logger.warning("Webhook signature mismatch")
                return Response({"error": "Invalid signature."}, status=status.HTTP_401_UNAUTHORIZED)

        payload = request.data
        idempotency_key = payload.get("transaction_id", str(uuid.uuid4()))

        # Log the webhook
        log, created = PaymentGatewayLog.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "gateway":     payload.get("gateway", "fapshi"),
                "event_type":  payload.get("event", "payment.success"),
                "raw_payload": payload,
            },
        )
        if not created:
            logger.info("Duplicate webhook ignored", extra={"key": idempotency_key})
            return Response({"status": "ok", "duplicate": True})

        # Only process successful payments
        if payload.get("status") not in ("success", "SUCCESSFUL", "COMPLETED"):
            log.processed = True
            log.processing_error = f"Skipped: status={payload.get('status')}"
            log.save(update_fields=["processed", "processing_error"])
            return Response({"status": "ok"})

        try:
            txn = process_cashin(
                user_id          = payload["user_id"],
                amount           = payload["amount"],
                gateway_reference= idempotency_key,
                idempotency_key  = idempotency_key,
                currency         = payload.get("currency", "XAF"),
            )
            log.transaction = txn
            log.processed   = True
            log.save(update_fields=["transaction", "processed"])
        except Exception as exc:
            log.processing_error = str(exc)
            log.save(update_fields=["processing_error"])
            logger.error("Webhook processing failed", extra={"error": str(exc)})
            return Response(
                {"error": "Processing failed."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"status": "ok"})
