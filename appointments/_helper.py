from rest_framework.response import Response
from rest_framework import status

from .constant import WALLET_PIN_TOKEN_PREFIX
from .models import Appointment

from utils.exceptions import error_response

def _wallet_pin_token_key(seeker_id) -> str:
    return f"{WALLET_PIN_TOKEN_PREFIX}:{seeker_id}"

def _appointment_payload(appointment: Appointment) -> dict:
    return {
        "appointment_id": str(appointment.id),
        "provider_id": str(appointment.provider.id),
        "seeker_id": str(appointment.customer.id),
        "category": appointment.category.title,
        "category_slug": appointment.category.slug,
        "scheduled_date": str(appointment.scheduled_date),
        "scheduled_time": str(appointment.scheduled_time),
        "location_address": appointment.location_address,
        "quoted_price": str(appointment.quoted_price),
        "status": appointment.status,
    }

def _get_appointment_or_404(pk):
    try:
        return Appointment.objects.select_related(
            "provider__user", "customer__user", "category"
        ).prefetch_related("status_logs").get(id=pk), None
    except Appointment.DoesNotExist:
        return None, error_response(message="Appointment not found.",  status_code=status.HTTP_404_NOT_FOUND)