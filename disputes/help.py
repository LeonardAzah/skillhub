from .models import Dispute
from rest_framework.response import Response
from rest_framework import status

from utils.exceptions import error_response



def _get_dispute_qs(select_related=True):
    qs = Dispute.objects.all()
    if select_related:
        qs = qs.select_related(
            "appointment__customer",
            "appointment__provider__user",
            "appointment__category",
            "raised_by",
            "resolved_by",
        ).prefetch_related("evidence__uploaded_by")
    return qs


def _get_dispute_or_404(pk):
    try:
        return _get_dispute_qs().get(id=pk), None
    except Dispute.DoesNotExist:

        return None, error_response(
            message="Dispute not found.",
            status=status.HTTP_404_NOT_FOUND

        )

def _is_dispute_party(user, dispute):
    return (
        dispute.appointment.customer.user_id == user.id
        or dispute.appointment.provider.user_id == user.id
    )


def _dispute_payload(dispute: Dispute) -> dict:
    apt = dispute.appointment
    return {
        "dispute_id":     str(dispute.id),
        "appointment_id": str(apt.id),
        "seeker_id":      str(apt.customer.id),
        "provider_id":    str(apt.provider.id),
        "status":         dispute.status,
    }