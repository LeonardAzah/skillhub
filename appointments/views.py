import logging
from datetime import date, timedelta, time

from django.db import transaction

from rest_framework import status
from rest_framework.permissions import  IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView

from .models import Appointment, ProviderAvailability
from .serializers import (
    ProviderAvailabilitySerializer, 
    CreateAppointmentSerializer, 
    AppointmentListSerializer, 
    AppointmentSerializer,
    AcceptAppointmentSerializer,
    RejectAppointmentSerializer,
    StartAppointmentSerializer,
    CompleteAppointmentSerializer,
    ConfirmAppointmentSerializer,
    CancleAppointmentSerializer,
    DisputeAppointmentSerializer,

    )

from .helper import _get_appointment_or_404, _appointment_payload

from accounts.models import ProviderProfile, User
from utils.permissions import  IsProvider, IsVerified
from notifications.publisher import publish_event
from utils.events import EventType
from utils.exceptions import error_response

logger = logging.getLogger(__name__)


class IsAppointmentParty(BasePermission):
    """Allow the customer, the provider, or staff/admin."""

    def has_object_permission(self, request, view, obj: Appointment) -> bool:
        user = request.user
        return (
            obj.customer_id == user.id
            or obj.provider.user_id == user.id
            or user.role == User.Role.ADMIN
            or user.is_staff
        )

class ProviderAvailabilityView(APIView):
    """
    GET /api/v1/appointments/providers/{provider_id}/availability/
    Returns available appointment slots for the next 30 days.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, provider_id):
        try:
            provider = ProviderProfile.objects.get(id=provider_id)
        except ProviderProfile.DoesNotExist:
            return error_response(
                message="Provider not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        today = date.today()
        end_date = today + timedelta(days=30)

        # Get blocked availability slots.
        blocked = ProviderAvailability.objects.filter(
            provider=provider,
            blocked_date__range=(today, end_date),
        )

        blocked_set = {
            (item.blocked_date, item.blocked_start)
            for item in blocked
        }

        # Get appointments that make a slot unavailable.
        appointments = Appointment.objects.filter(
            provider=provider,
            scheduled_at__date__range=(today, end_date),
            status__in=[
                Appointment.Status.PENDING,
                Appointment.Status.ACCEPTED,
                Appointment.Status.IN_PROGRESS,
            ],
        )

        busy_slots = {
            (
                appointment.scheduled_at.date(),
                appointment.scheduled_at.time().replace(
                    minute=0,
                    second=0,
                    microsecond=0,
                ),
            )
            for appointment in appointments
        }

        available = []

        current = today

        while current <= end_date:
            for hour in range(7, 19):
                start = time(hour, 0)
                end = time(hour + 1, 0)

                slot_key = (current, start)

                if slot_key in blocked_set:
                    continue

                if slot_key in busy_slots:
                    continue

                available.append(
                    {
                        "date": current,
                        "start": start,
                        "end": end,
                    }
                )

            current += timedelta(days=1)

        return Response(
            {
                "success": True,
                "message": "Successfully retrieved available time slots.",
                "data": {
                    "count": len(available),
                    "slots": available,
                },
            }
        )


class ProviderAvailabilityBlockView(APIView):
    """
    POST /api/v1/appointments/providers/availability/
    Allows the authenticated provider to block an availability slot.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            provider = ProviderProfile.objects.get(user=request.user)
        except ProviderProfile.DoesNotExist:
            return error_response(
                message="Provider profile not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProviderAvailabilitySerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        blocked_slot = serializer.save(provider=provider)

        return Response(
            {
                "success": True,
                "message": "Slot blocked successfully.",
                "data": ProviderAvailabilitySerializer(
                    blocked_slot
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )
class ProviderAvailabilityDeleteView(APIView):
    """DELETE /api/v1/appointment/availability/{block_id}"""
    permission_classes=[IsAuthenticated, IsProvider]

    def delete(Self, request, blocked_id):
        try:
            block = ProviderAvailability.objects.get(id=blocked_id, provider__user=request.user)
            print(block)

        except ProviderAvailability.DoesNotExist:
            return error_response(
                message="Block not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        block.delete()

        return Response(
            
            status=status.HTTP_204_NO_CONTENT
        )


class AppointmentListCreateView(ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return CreateAppointmentSerializer if self.request.method == "POST" else AppointmentListSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsVerified()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = Appointment.objects.select_related(
            "provider__user",
            "provider__user__seeker_profile",
            "provider__user__provider_profile",
            "customer__seeker_profile",
            "customer__provider_profile",
            "category",
        )

        if user.role == User.Role.SEEKER:
            qs = qs.filter(customer=user)
        elif user.role == User.Role.PROVIDER:
            qs = qs.filter(provider__user=user)
        elif user.role == User.Role.ADMIN or user.is_staff:
            pass  # admins see everything
        else:
            qs = qs.none()

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        apt: Appointment = serializer.save()

        publish_event(EventType.APPOINTMENT_CREATED, {
            **_appointment_payload(apt),
            "notes": apt.notes,
        })

        output = AppointmentSerializer(apt, context=self.get_serializer_context())
        return Response(
            {
                "success":True,
                "message":"Appointment list retrived successfully.",
                "data":output.data,
            },
             status=status.HTTP_201_CREATED
            )


class AppointmentDetailView(RetrieveAPIView):
    """GET /api/v1/appointments/{id}"""
    queryset = Appointment.objects.select_related(
        "provider__user",
        "provider__user__seeker_profile",
        "provider__user__provider_profile",
        "customer__seeker_profile",
        "customer__provider_profile",
        "category",
        )
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated, IsAppointmentParty]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "message": "Appointment retrieved successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

class AcceptAppointmentView(APIView):
    """POST /api/v1/appointments/{id}/accept - provider only"""
    permission_classes = [IsAuthenticated, IsProvider]

    def post(self, request, pk):
        apt, err = _get_appointment_or_404(pk)
        if err:
            return err
        if apt.provider.user != request.user:
            return error_response(
                message="Forbidden.",
                status_code=status.HTTP_403_FORBIDDEN
            )

        AcceptAppointmentSerializer(data={}, context={"appointment": apt}).is_valid(raise_exception=True)

        apt.transition_to(Appointment.Status.ACCEPTED, actor=request.user)

        publish_event(EventType.APPOINTMENT_ACCEPTED, _appointment_payload(apt))

        return Response(
            {
                "success":True,
                "message":"Appointment accepted successfully.",
                "data":AppointmentSerializer(apt).data
            },
            status=status.HTTP_200_OK
        )

class RejectAppointmentView(APIView):
    """POST /api/v1/appointments/{id}/reject - provider only"""

    permission_classes = [IsAuthenticated, IsProvider]

    def post(self, request, pk):
        apt, err = _get_appointment_or_404(pk)

        if err:
            return err
        if apt.provider.user != request.user:
            return error_response(
                message="Forbidden.",
                status_code=status.HTTP_403_FORBIDDEN
            )

        serializer = RejectAppointmentSerializer(data=request.data, context={"appointment":apt})
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get("reason", "")
        apt.transition_to(Appointment.Status.REJECTED, actor=request.user, reason=reason)

        publish_event(EventType.APPOINTMENT_REJECTED, {**_appointment_payload(apt), "reason": reason})

        return Response(
             {
                "success":True,
                "message":"Appointment Recjected successfully.",
                "data": AppointmentSerializer(apt).data
            },
            status=status.HTTP_200_OK
        )


class StartAppointmentView(APIView):
    """POST /api/v1/appointments/{id}/start - provider only"""

    permission_classes= [IsAuthenticated, IsProvider]

    def post(self, request, pk):
        apt, err = _get_appointment_or_404(pk)

        if err:
            return err

        if apt.provider.user != request.user:
            return error_response(
                message="Forbidden.",
                status_code=status.HTTP_403_FORBIDDEN
            )

        StartAppointmentSerializer(data={}, context={"appointment":apt}).is_valid(raise_exception=True)

        apt.transition_to(Appointment.Status.IN_PROGRESS, actor=request.user)

        publish_event(EventType.APPOINTMENT_STARTED, _appointment_payload(apt))

        return Response(
            {
                "success":True,
                "message":"Appointment started successfully.",
                "data": AppointmentSerializer(apt).data

            },
            status=status.HTTP_200_OK
        )

class CompleteAppointmentView(APIView):
    """POST /api/v1/appointments/{id}/complete - provider only """
    permission_classes=[IsAuthenticated, IsProvider]

    def post(self, request, pk):

        apt, err = _get_appointment_or_404(pk)

        if err:
            return err

        if apt.provider.user != request.user:
            return error_response(
                        message="Forbidden.",
                        status_code=status.HTTP_403_FORBIDDEN
                    )

        serializer = CompleteAppointmentSerializer(data=request.data, context={"appointment": apt})
        serializer.is_valid(raise_exception=True)

        validated_value = serializer.validated_data

        apt.completion_proof = validated_value["completion_proof"]
        apt.completion_notes = validated_value.get("completion_notes", "")

        if validated_value.get("final_price"):
            apt.final_price = validated_value["final_price"]

        apt.save(update_fields=["completion_proof", "completion_notes", "final_price", "updated_at"])

        apt.transition_to(Appointment.Status.COMPLETED, actor=request.user)

        publish_event(EventType.APPOINTMENT_COMPLETED, {
            **_appointment_payload(apt),
            "completion_proof": apt.completion_proof,
        })

        return Response(
                    {
                        "success":True,
                        "message":"Appointment marked as completted.",
                        "data": AppointmentSerializer(apt).data
        
                    },
                    status=status.HTTP_200_OK
                )


class ConfirmAppointmentView(APIView):
    """POST /api/v1/appointments/{id}/confirm - triggers escrow release"""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        apt, err = _get_appointment_or_404(pk)
        if err:
            return err
        if apt.customer.id != request.user:
             return error_response(
                        message="Forbidden.",
                        status_code=status.HTTP_403_FORBIDDEN
                    )

        ConfirmAppointmentSerializer(data={}, context={"appointment":apt}).is_valid(raise_exception=True)

        with transaction.atomic():
            apt.transition_to(Appointment.Status.CONFIRMED, actor=request.user)
            ProviderProfile.objects.filter(pk=apt.provider_id).update(
                total_jobs=apt.provider.total_jobs + 1
            )

        publish_event(EventType.APPOINTMENT_CONFIRMED, _appointment_payload(apt))

        return Response(
            {
                "success": True,
                "message": "Appointment confirmed successfully.",
                "data": AppointmentSerializer(apt).data,
            },
            status=status.HTTP_200_OK,
        )


class CancelAppointmentView(APIView):
    """POST /api/v1/appointments/{id}/cancel - either party or admin"""
    permission_classes = [IsAuthenticated, IsAppointmentParty]

    def post(self, request, pk):
        apt, err = _get_appointment_or_404(pk)

        if err:
            return err

        user = request.user

        serializer = CancleAppointmentSerializer(data=request.data, context={"appointment": apt})

        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data.get("reason", "")

        apt.transition_to(Appointment.Status.CANCELLED, actor=user, reason=reason)

        publish_event(EventType.APPOINTMENT_CANCELLED, {
             **_appointment_payload(apt),
            "reason":       reason,
            "cancelled_by": user.role,
        })

        return Response(
                    {
                        "success": True,
                        "message": "Appointment cancelled.",
                        "data": AppointmentSerializer(apt).data,
                    },
                    status=status.HTTP_200_OK,
                )

class DisputeAppointmentView(APIView):
    """POST /api/v1/appointments/{id}/dispute - seeker only, within 48h of COMPLETED"""

    permission_classes = [IsAuthenticated, IsAppointmentParty]

    def post(self, request, pk):
        apt, err = _get_appointment_or_404(pk)
        if err:
            return err

        serializer = DisputeAppointmentSerializer(data=request.data, context={"appointment": apt})
        serializer.is_valid(raise_exception=True)
        seeker_statement = serializer.validated_data["seeker_statement"]

        apt.transition_to(Appointment.Status.DISPUTED, actor=request.user)

        from disputes.models import Dispute, DisputeAuditLog
        from disputes.services import write_audit, freeze_escrow_for_dispute

        dispute, _created = Dispute.objects.get_or_create(
            appointment=apt,
            defaults={
                "raised_by": request.user,
                "seeker_statement": seeker_statement,
                "status": Dispute.Status.OPEN,
            },
        )

        # Freese escrow
        freeze_escrow_for_dispute(str(apt.id))

        #Write opening audit entry
        write_audit(
            dispute=dispute,
            action=DisputeAuditLog.Action.RAISED,
            actor=request.user,
            description=seeker_statement[:200]
        )

        publish_event(EventType.DISPUTE_RAISED, {
            **_appointment_payload(apt),
            "seeker_statement": serializer.validated_data["seeker_statement"],
            "dispute_id":       None,
        })

        return Response(
                            {
                                "success": True,
                                "message": "Dispute Created.",
                                "data": AppointmentSerializer(apt).data,
                            },
                            status=status.HTTP_200_OK,
                        )



