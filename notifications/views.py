from django.urls import path
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, NotificationPreference, EmailLog
from .serializers import NotificationSerializer, NotificationPreferenceSerializer, UpdatePreferenceSerializer

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from utils.exceptions import error_response

# Create your views here.


class NotificationListView(ListAPIView):
    """
    GET /api/v1/notifications/
    List user notifications, newest first, paginated (20/page).
    Supports ?unread_only=true filter.
    """
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
        OrderingFilter,
    ]

    filterset_fields = ["notification_type", "event_type", "is_read"]

    search_fields = [
        "title",
        "body",
    ]

    ordering_fields = ["created_at", "is_read"]
    ordering = ["-created_at"] 

    serializer_class   = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by("-created_at")

    def list(self, request, *args, **kwargs):
        response    = super().list(request, *args, **kwargs)
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        response.data["unread_count"] = unread_count
        return response


class NotificationMarkReadView(APIView):
    """
    PATCH /api/v1/notifications/{id}/read/
    Mark a single notification as read.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            notif = Notification.objects.get(id=pk, user=request.user)
        except Notification.DoesNotExist:
            return error_response("Notification not found.",status.HTTP_404_NOT_FOUND)

        notif.is_read = True
        notif.save(update_fields=["is_read"])
        return Response({
            "success": True,
                "message": "Notification marked as read successfully.",
                "data": NotificationSerializer(notif).data,
        }
            
            )


class NotificationMarkAllReadView(APIView):
    """
    POST /api/v1/notifications/read-all/
    Mark all of the authenticated user's notifications as read.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({
                            "success": True,

            "message": f"{count} notification(s) marked as read.", "data": count})


class NotificationPreferencesView(APIView):
    """
    GET  /api/v1/notifications/preferences/ — get user preferences
    PATCH /api/v1/notifications/preferences/ — update preferences
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        prefs = NotificationPreference.objects.filter(user=request.user)
        # Include all possible types, using defaults for unset ones
        all_types     = {c[0] for c in Notification.NotificationType.choices}
        existing_map  = {p.notification_type: p for p in prefs}
        result        = []
        for ntype in sorted(all_types):
            if ntype in existing_map:
                result.append(NotificationPreferenceSerializer(existing_map[ntype]).data)
            else:
                result.append({
                    "notification_type": ntype,
                    "push_enabled":      True,
                    "email_enabled":     True,
                    "updated_at":        None,
                })
        return Response(result)

    def patch(self, request):
        serializer = UpdatePreferenceSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(
            NotificationPreferenceSerializer(updated, many=True).data,
            status=status.HTTP_200_OK,
        )