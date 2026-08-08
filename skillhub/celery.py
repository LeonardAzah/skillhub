import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "skillhub.settings")

app = Celery("skillhub")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


# Periodic task schedule (Celery Beat)
app.conf.beat_schedule = {
    # Prune stale FCM device tokens after 90 days
    "prune-stale-device-tokens": {
        "task": "accounts.tasks.prune_stale_device_tokens",
        "schedule": crontab(hour=3, minute=0),
    },

    # Auto-release escrow 48h after COMPLETED status
    "auto-release-escrow": {
        "task": "apps.accounts.tasks.auto_release_escrow",
        "schedule": crontab(minute="*/5"),
    },

    #Expire PENDING appointments not accepted within 24h
     "expire-pending-appointments": {
        "task": "apps.accounts.tasks.expire_pending_appointments",
        "schedule": crontab(minute="*/10"),
    },

}

app.conf.timezone = "Africa/Douala"
