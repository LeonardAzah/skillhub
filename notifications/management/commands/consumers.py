import json
import logging
import signal
import time

import pika
from django.core.management.base import BaseCommand

from notifications.handlers import dispatch
from notifications.publisher import (
    EXCHANGE_NAME,
    QUEUE_NAME,
    _declare_topology,
    _get_connection_params,
)

logger = logging.getLogger(__name__)

PREFETCH_COUNT   = 10    # max unacknowledged messages per consumer
MAX_RETRIES      = 5     # header-based retry limit before DLQ
RECONNECT_DELAYS = [2, 4, 8, 16, 32, 60]  # exponential backoff (seconds)


class Command(BaseCommand):
    help = "Long-running RabbitMQ consumer for the notification module."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prefetch",
            type=int,
            default=PREFETCH_COUNT,
            help="Max unacknowledged messages (default: 10).",
        )

    def handle(self, *args, **options):
        self._stop = False
        self._prefetch = options["prefetch"]

        # Graceful shutdown on SIGINT / SIGTERM
        signal.signal(signal.SIGINT,  self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        self.stdout.write(self.style.SUCCESS(
            "notification consumer starting…\n"
            f"  Queue:     {QUEUE_NAME}\n"
            f"  Exchange:  {EXCHANGE_NAME}\n"
            f"  Prefetch:  {self._prefetch}\n"
        ))

        attempt = 0
        while not self._stop:
            try:
                self._run_consumer()
                attempt = 0  # reset on clean exit
            except (pika.exceptions.AMQPConnectionError,
                    pika.exceptions.StreamLostError,
                    pika.exceptions.ConnectionClosedByBroker) as exc:
                if self._stop:
                    break
                delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
                logger.warning(
                    "RabbitMQ connection lost — reconnecting",
                    extra={"error": str(exc), "retry_in_seconds": delay, "attempt": attempt + 1},
                )
                self.stdout.write(self.style.WARNING(
                    f"Connection lost ({exc}). Reconnecting in {delay}s… (attempt {attempt + 1})"
                ))
                time.sleep(delay)
                attempt += 1
            except Exception as exc:
                logger.exception("Unexpected consumer error", extra={"error": str(exc)})
                if self._stop:
                    break
                time.sleep(5)

        self.stdout.write(self.style.SUCCESS("Consumer stopped cleanly."))

    # ── Main consumer loop ────────────────────────────────────────────────────

    def _run_consumer(self) -> None:
        params = _get_connection_params()
        conn   = pika.BlockingConnection(params)
        ch     = conn.channel()

        _declare_topology(ch)
        ch.basic_qos(prefetch_count=self._prefetch)
        ch.basic_consume(queue=QUEUE_NAME, on_message_callback=self._on_message)

        logger.info("Consumer connected and waiting for events")
        self.stdout.write("  Waiting for events…  (Ctrl+C to stop)\n")

        try:
            ch.start_consuming()
        except KeyboardInterrupt:
            ch.stop_consuming()
        finally:
            if conn.is_open:
                conn.close()

    # ── Message callback ──────────────────────────────────────────────────────

    def _on_message(
        self,
        channel: pika.adapters.blocking_connection.BlockingChannel,
        method:  pika.spec.Basic.Deliver,
        properties: pika.spec.BasicProperties,
        body: bytes,
    ) -> None:
        """
        Called for every message delivered from the queue.
        Deserialises the envelope, calls dispatch(), then acks.
        On failure, increments x-death count; nacks after MAX_RETRIES.
        """
        routing_key = method.routing_key
        try:
            envelope = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.error(
                "Malformed message — sending to DLQ",
                extra={"routing_key": routing_key, "error": str(exc)},
            )
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        event_type  = envelope.get("event_type", routing_key)
        payload     = envelope.get("payload", {})
        event_id    = envelope.get("event_id", "")
        occurred_at = envelope.get("occurred_at", "")

        # Check header-based retry count (set by RabbitMQ dead-letter mechanism)
        death_count = self._get_death_count(properties)
        if death_count >= MAX_RETRIES:
            logger.error(
                "Event exceeded max retries — discarding",
                extra={"event_type": event_type, "event_id": event_id, "death_count": death_count},
            )
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        try:
            print(f"Received event: {event_type}")
            handlers_called = dispatch(event_type, payload, event_id=event_id)
            channel.basic_ack(delivery_tag=method.delivery_tag)
            logger.info(
                "Event processed",
                extra={
                    "event_type":     event_type,
                    "event_id":       event_id,
                    "occurred_at":    occurred_at,
                    "handlers_called":handlers_called,
                },
            )
        except Exception as exc:
            logger.exception(
                "Handler error — nacking message",
                extra={"event_type": event_type, "event_id": event_id, "error": str(exc)},
            )
            # nack without requeue → goes to dead-letter exchange for retry
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _get_death_count(properties: pika.spec.BasicProperties) -> int:
        """Extract x-death retry count from message headers."""
        headers = getattr(properties, "headers", None) or {}
        deaths  = headers.get("x-death", [])
        if deaths:
            return sum(d.get("count", 1) for d in deaths)
        return 0

    def _handle_shutdown(self, signum, frame):
        logger.info("Shutdown signal received", extra={"signal": signum})
        self.stdout.write(self.style.WARNING("\nShutting down consumer…"))
        self._stop = True
