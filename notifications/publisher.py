"""
RabbitMQ event publisher.

Any module publishes a domain event with a single call:

    from notifications.publisher import publish_event
    from notifications.events import EventType

    publish_event(EventType.APPOINTMENT_ACCEPTED, {
        "appointment_id": str(appointment.id),
        "provider_id":    str(appointment.provider_id),
        "seeker_id":      str(appointment.seeker_id),
        ...
    })
"""
import json
import logging
from typing import Any
import traceback

import pika
from django.conf import settings

from .events import Event, EventType
from .tasks import deliver_event_via_celery

logger = logging.getLogger(__name__)

# Exchange / queue names kept in one place
EXCHANGE_NAME = "skillhub.events"
QUEUE_NAME    = "skillhub.notifications"
DLX_EXCHANGE  = "skillhub.events.dlx"      # dead-letter exchange
DLQ_NAME      = "skillhub.notifications.dlq"


def _get_connection_params() -> pika.ConnectionParameters:
    """Build pika ConnectionParameters from settings."""
    url = getattr(settings, "RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    params = pika.URLParameters(url)
    params.heartbeat = 60
    params.blocked_connection_timeout = 30
    params.connection_attempts = 3
    params.retry_delay = 2
    return params


def _declare_topology(channel: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """
    Idempotently declare exchange, DLX, main queue, and DLQ.
    Safe to call on every publish; pika no-ops if already declared.
    """
    # Dead-letter exchange (fanout — DLQ gets everything)
    channel.exchange_declare(
        exchange=DLX_EXCHANGE,
        exchange_type="fanout",
        durable=True,
    )
    channel.queue_declare(
        queue=DLQ_NAME,
        durable=True,
    )
    channel.queue_bind(exchange=DLX_EXCHANGE, queue=DLQ_NAME)

    # Main topic exchange
    channel.exchange_declare(
        exchange=EXCHANGE_NAME,
        exchange_type="topic",
        durable=True,
    )
    # Main notification queue — receives ALL events (routing key "#")
    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_EXCHANGE,
            "x-message-ttl":          86_400_000,   # 24h TTL
            "x-max-length":           100_000,       # max 100k pending messages
        },
    )
    channel.queue_bind(
        exchange=EXCHANGE_NAME,
        queue=QUEUE_NAME,
        routing_key="#",    # subscribe to every routing key
    )


def publish_event(event_type: str, payload: dict | None = None) -> bool:
    """
    Publish a domain event onto the RabbitMQ topic exchange.
    Returns True on success, False when falling back to Celery.
    """
    payload = payload or {}
    event   = Event(event_type=event_type, payload=payload)
    body    = json.dumps(event.to_dict(), default=str)

    try:
        params  = _get_connection_params()
        conn    = pika.BlockingConnection(params)
        channel = conn.channel()
        _declare_topology(channel)

        channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=event_type,     # routing key = event type string
            body=body.encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,        # persistent (survives broker restart)
                content_type="application/json",
                message_id=event.event_id,
                timestamp=int(__import__("time").time()),
                app_id="skillhub",
            ),
            mandatory=False,
        )
        conn.close()
        logger.debug(
            "Event published to RabbitMQ",
            extra={"event_type": event_type, "event_id": event.event_id},
        )
        return True

    except Exception as exc:
        # Fallback: enqueue via Celery so the event is not lost
        logger.error(traceback.format_exc())
        logger.warning(
            "RabbitMQ publish failed - falling back to Celery task",
            extra={"event_type": event_type, "error": str(exc)},
        )
        try:
            
            deliver_event_via_celery.apply_async(
                kwargs={"event_type": event_type, "payload": payload, "event_id": event.event_id},
                queue="notifications",
            )
        except Exception as celery_exc:
            logger.error(
                "Both RabbitMQ and Celery fallback failed for event",
                extra={
                    "event_type":  event_type,
                    "rmq_error":   str(exc),
                    "celery_error":str(celery_exc),
                },
            )
        return False
