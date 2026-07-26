"""
Celery tasks:
  send_push_notification_task   — FCM delivery via firebase-admin
  send_email_notification_task  — SES delivery via Django email
  deliver_event_via_celery      — RabbitMQ fallback handler (routes to dispatch)
  process_notification_event    — called by RabbitMQ consumer; wraps dispatch()
"""
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .handlers import dispatch
from accounts.models import User
from .models import EmailLog


logger = logging.getLogger(__name__)


# ─── FCM Push ─────────────────────────────────────────────────────────────────

@shared_task(
    name="notifications.send_push",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    queue="notifications",
)
def send_push_notification_task(
    self,
    user_id: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> dict:
    """
    SRS §10.2 — Send FCM push notification to all active device tokens for a user.

    Delivery:
      1. Look up all DeviceToken rows for user (is_active=True)
      2. Call firebase_admin.messaging.send_each()
      3. Mark stale tokens inactive on UNREGISTERED response
      4. Retry up to 3 times on transient FCM errors
    """
    from accounts.models import DeviceToken

    data = data or {}
    tokens = list(
        DeviceToken.objects.filter(user_id=user_id, is_active=True).values_list("token", "platform", "id")
    )
    if not tokens:
        logger.debug("No active device tokens for user", extra={"user_id": user_id})
        return {"status": "skipped", "reason": "no_tokens"}

    try:
        import firebase_admin
        from firebase_admin import messaging, credentials

        # Lazy initialisation — only runs once per worker process
        if not firebase_admin._apps:
            cred_path = getattr(settings, "FIREBASE_CREDENTIALS_PATH", None)
            if cred_path:
                cred = credentials.Certificate(cred_path)
            else:
                cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)

        messages = [
            messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data={k: str(v) for k, v in data.items()},  # FCM requires str values
                token=token,
            )
            for token, _, _ in tokens
        ]

        response = messaging.send_each(messages)
        stale_ids = []

        for i, (token, platform, token_id) in enumerate(tokens):
            if i < len(response.responses):
                resp = response.responses[i]
                if not resp.success:
                    error_code = getattr(resp.exception, "code", "")
                    if error_code in ("UNREGISTERED", "INVALID_ARGUMENT"):
                        stale_ids.append(token_id)

        if stale_ids:
            DeviceToken.objects.filter(id__in=stale_ids).update(is_active=False)
            logger.info("Deactivated stale device tokens", extra={"count": len(stale_ids)})

        logger.info(
            "Push notifications sent",
            extra={
                "user_id":    user_id,
                "success":    response.success_count,
                "failure":    response.failure_count,
            },
        )
        return {"status": "ok", "success": response.success_count, "failure": response.failure_count}

    except ImportError:
        # firebase_admin not installed — happens in test / dev without credentials
        logger.warning("firebase_admin not available — push skipped", extra={"user_id": user_id})
        return {"status": "skipped", "reason": "firebase_not_configured"}

    except Exception as exc:
        logger.error("FCM push failed", extra={"user_id": user_id, "error": str(exc)})
        raise self.retry(exc=exc)


# Email

@shared_task(
    name="notifications.send_email",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="notifications",
)
def send_email_notification_task(
    self,
    user_id: str,
    template: str,
    context: dict | None = None,
    subject: str = "",
) -> dict:
    """
    Render HTML template and dispatch via Django email backend.
    Logs every attempt to EmailLog.
    """
    context = context or {}

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("Email skipped - user not found", extra={"user_id": user_id})
        return {"status": "skipped", "reason": "user_not_found"}

    event_id = context.get("event_id", "")
    log = EmailLog.objects.create(
        user=user,
        to_email=user.email,
        subject=subject or "SkillHub Notification",
        template=template,
        event_id=event_id,
        status=EmailLog.Status.SENT,
    )

    try:
        full_context = {
            "user":          user,
            "platform_name": "SkillHub",
            **context,
        }
        html_message   = render_to_string(template, full_context)
        plain_message  = strip_tags(html_message)
        final_subject  = subject or "SkillHub Notification"

        send_mail(
            subject=final_subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        log.status = EmailLog.Status.DELIVERED
        log.save(update_fields=["status"])
        logger.info("Email sent", extra={"user_id": user_id, "template": template})
        return {"status": "ok", "to": user.email}

    except Exception as exc:
        log.status       = EmailLog.Status.FAILED
        log.error_detail = str(exc)
        log.save(update_fields=["status", "error_detail"])
        logger.error("Email send failed", extra={"user_id": user_id, "template": template, "error": str(exc)})
        raise self.retry(exc=exc)


# RabbitMQ fallback (Celery route when RMQ is unavailable)

@shared_task(
    name="notifications.deliver_event_via_celery",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    queue="notifications",
)
def deliver_event_via_celery(
    self,
    event_type: str,
    payload: dict | None = None,
    event_id: str = "",
) -> dict:
    """
    Fallback task — called by publisher.publish_event() when RabbitMQ
    is unreachable.  Routes the event through the same dispatch() pipeline
    so no notification is ever silently dropped.
    """
    payload = payload or {}
    try:
        count = dispatch(event_type, payload, event_id=event_id)
        logger.info(
            "Event dispatched via Celery fallback",
            extra={"event_type": event_type, "handlers_called": count},
        )
        return {"status": "ok", "handlers": count}
    except Exception as exc:
        logger.exception("Celery fallback dispatch failed", extra={"event_type": event_type})
        raise self.retry(exc=exc)


# Inline processor (called by RabbitMQ consumer)

@shared_task(
    name="notifications.process_event",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    queue="notifications",
)
def process_notification_event(
    self,
    event_type: str,
    payload: dict | None = None,
    event_id: str = "",
) -> dict:
    """
    Called by the RabbitMQ consumer management command after deserialising
    a message from the boloconnect.notifications queue.
    Hands off to handlers.dispatch() and acks the message.
    """
    from .handlers import dispatch
    payload = payload or {}
    try:
        count = dispatch(event_type, payload, event_id=event_id)
        return {"status": "ok", "event_type": event_type, "handlers": count}
    except Exception as exc:
        logger.exception("process_notification_event failed", extra={"event_type": event_type})
        raise self.retry(exc=exc)
