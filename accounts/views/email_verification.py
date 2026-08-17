import logging
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.helpers import _frontend_url, _setting


from ..models import User, EmailVerificationToken
from ..serializers import EmailVerifySerializer, ResendVerificationSerializer, UserSummarySerializer

from utils.events import EventType
from notifications.publisher import publish_event


logger = logging.getLogger(__name__)


class VerifyEmailView(APIView):
    """
    GET /api/v1/auth/verify-email/{token}/
    Consume verification token.
    """
    permission_classes = [AllowAny]

    def get(self, request, token):
        serializer = EmailVerifySerializer(data={"token": token})
        serializer.is_valid(raise_exception=True)
        user: User = serializer.save()

        publish_event(EventType.USER_EMAIL_VERIFIED, {
            "user_id":str(user.id),
            "email": user.email,
        })
    
        return Response(
            {
                "success": True,
                "message": "Email verified successfully. You can now complete your profile.",
                "data":    {"user": UserSummarySerializer(user).data},
            },
            status=status.HTTP_200_OK,
        )


class ResendVerificationView(APIView):
    """
    POST /api/v1/auth/resend-verification/

    Emits
    ─────
    accounts.user.verification_requested  → same handler as initial send
    """
    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user: User = serializer.context.get("user")

        if user:
            EmailVerificationToken.objects.filter(user=user, is_used=False).update(is_used=True)
            vtoken = EmailVerificationToken.objects.create(user=user)

            publish_event(
                EventType.USER_VERIFICATION_REQUESTED,
                {
                    "user_id": str(user.id),
                    "email": user.email,
                    "username": user.username,
                    "token": str(vtoken.token),
                    "verify_url": f"{_frontend_url()}/auth/verify-email/{vtoken.token}",
                    "expiry_hours":_setting("EMAIL_VERIFICATION_EXPIRY_HOURS", 24)
                }
            )
           
        # Always 200 — prevents user enumeration
        return Response(
            {
                "success": True,
                "message": "If your email is registered and unverified, a new link has been sent.",
                "data":    {},
            },
            status=status.HTTP_200_OK,
        )
