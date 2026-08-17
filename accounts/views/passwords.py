import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.throttling import AnonRateThrottle
from drf_spectacular.utils import extend_schema


from utils.events import EventType
from notifications.publisher import publish_event
from utils.helpers import get_client_ip, _frontend_url, _setting


from ..models import User, PasswordResetToken

from ..serializers import (
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    SetNewPasswordSerializer,
    ChangePasswordSerializer
)

logger = logging.getLogger(__name__)


@extend_schema(
    request=PasswordResetRequestSerializer,
    responses=PasswordResetRequestSerializer,
)
class PasswordResetRequestView(APIView):
    """Initiate password reset."""

    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data, context={"request":request})
        serializer.is_valid(raise_exception=True)
        user:User = serializer.context.get("user")

        if user:
            PasswordResetToken.objects.filter(user=user, is_used=False).update(is_used=True)
            reset_token = PasswordResetToken.objects.create(
                user=user,
                ip_address = get_client_ip(request),
            )

            publish_event(
                EventType.USER_PASSWORD_RESET, {
                    "user_id":      str(user.id),
                    "email":        user.email,
                    "username":     user.username,
                    "token":        str(reset_token.token),
                    "reset_url":    f"{_frontend_url()}/auth/password/reset/confirm/{reset_token.token}",
                    "expiry_hours": _setting("PASSWORD_RESET_EXPIRY_HOURS", 1),
                    "ip_address":   reset_token.ip_address or "Unknown",
                },
            )

            return Response (
                {
                "success": True,
                "message": "A password reset link has been sent to your email.",
                "data":    {},
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response (
                            {
                            "success": True,
                            "message": "A password reset link has been sent to your email.",
                            "data":    {},
                            },
                            status=status.HTTP_200_OK,
                        )
class PasswordResetConfirmView(APIView):
    """Validate reset token"""

    permission_classes = [AllowAny]

    def get(self, request, token):
        serializer = PasswordResetConfirmSerializer(data={"token": token})
        serializer.is_valid(raise_exception=True)
        reset_token = serializer.validated_data["token"]
        return Response(
            {
                "success": True,
                "message": "Token is valid. Please submit your new password.",
                "data": {
                    "email": reset_token.user.email,
                    "token": str(reset_token.token),
                },
            },
            status=status.HTTP_200_OK,
        )
    
@extend_schema(
    request=SetNewPasswordSerializer,
    responses=SetNewPasswordSerializer,
)
class SetNewPasswordView(APIView):
    """Consume reset token, set new password."""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SetNewPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user:User = serializer.save()

        publish_event(EventType.USER_PASSWORD_CHANGED, {
            "user_id":  str(user.id),
            "email":    user.email,
            "username": user.username,
        })

        return Response(
            {
                "success": True,
                "message": "Password reset successfully. You can now log in with your new password.",
                "data":    {},
            },
            status=status.HTTP_200_OK,
        )

class ChangePasswordView(APIView):
    """Authenticated password change."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        user.invalidate_existing_tokens()

        publish_event(EventType.USER_PASSWORD_CHANGED, {
            "user_id":  str(user.id),
            "email":    user.email,
            "username": user.username,
        })

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        return Response(
            {
                "success": True,
                "message": "Password changed successfully.",
                "data": {
                    "access": str(access),
                    "refresh": str(refresh),
                },
            },
            status=status.HTTP_200_OK,
        )