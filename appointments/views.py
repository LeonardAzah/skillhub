import logging
from datetime import date, timedelta, time

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Appointment, ProviderAvailability
from .serializers import ProviderAvailabilitySerializer

from accounts.models import ProviderProfile
from utils.permissions import IsAdmin, IsProvider, IsSeeker, IsVerified
from notifications.publisher import publish_event
from notifications.events import EventType
from categories.models import Category, ProviderCategory
from utils.exceptions import error_response

logger = logging.getLogger(__name__)

# class ProviderAvailabilityView(APIView):
#     """
#     GET /api/v1/appointments/providers/{id}/availability
#     POST /api/v1/appointments/providers/{id}/availability
#     """

#     permission_classes = [IsAuthenticated]

#     def get(self, request, provider_id):
#         try:
#             provider = ProviderProfile.objects.get(id=provider_id)
#         except ProviderProfile.DoesNotExist:
#             return error_response(message="Provider not found.", status_code=status.HTTP_404_NOT_FOUND)

#         today = date.today()
#         end_date = today + timedelta(days=30)

#         blocked = ProviderAvailability.objects.filter(
#             provider=provider,
#             blocked_date__gte=today,
#             blocked_date__lte=end_date, 
#         )

#         busy_slots = set(
#             Appointment.objects.filter(
#                 provider=provider,
#                 scheduled_at__gte=today,
#                 scheduled_at__lte=end_date,
#                 status__in=[Appointment.Status.PENDING, Appointment.Status.ACCEPTED,
#                         Appointment.Status.IN_PROGRESS],
#             ).values_list("scheduled_at")

#         )

#         blocked_set = {

#            {date.blocked_date, date.blocked_start} for date in blocked
#         }

#         available = []
#         current = today

#         while current <= end_date:
#             for hrs in range(7, 19):
#                 start = time(hrs, 0)
#                 end = time(hrs +1 , 0)

#                 if(current, start) not in blocked_set and (current, start) not in busy_slots:
#                     available.append({"date": current, "start":start, "end": end})
#             current += timedelta(days=1)
#         return Response({
#             "success":True,
#             "message":"Success retrieved available time",
#             "data":{
#                 "count": len(available), "slots": available
#             }
#         })

#     def post(self, request):
#         try:
#             provider = ProviderProfile(user=request.user)
#         except ProviderProfile.DoesNotExist:
#             return error_response(
#                 message="Not found or not your profile.",
#                 status_code=status.HTTP_404_NOT_FOUND
#             )
#         serializer = ProviderAvailabilitySerializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
#         block = serializer.save(provider=provider)
#         return Response(
#             {
#                 "success":True,
#                 "message":"Slot blocked successfully",
#                 "data":{
#                     ProviderAvailabilitySerializer(block).data
#                 }
#             },
#             status=status.HTTP_201_CREATED
#         )


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