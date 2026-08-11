import logging
from datetime import date, timedelta, time

from rest_framework import status, permissions
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView

from .models import Appointment, ProviderAvailability
from .serializers import ProviderAvailabilitySerializer, CreateAppointmentSerializer, AppointmentListSerializer, AppointmentSerializer

from accounts.models import ProviderProfile, User
from utils.permissions import IsAdmin, IsProvider, IsVerified
from notifications.publisher import publish_event
from notifications.events import EventType
from categories.models import Category, ProviderCategory
from utils.exceptions import error_response

logger = logging.getLogger(__name__)


class IsAppointmentParty(permissions.BasePermission):
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
        return Response(output.data, status=status.HTTP_201_CREATED)


class AppointmentDetailView(RetrieveAPIView):
    """GET /api/v1/appointments/{id}"""
    queryset = Appointment.objects.select_related("provider__user", "customer", "category")
    serializer_class = AppointmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsAppointmentParty]