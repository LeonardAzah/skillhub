"""Device token management: register and delete FCM tokens."""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import DeviceToken
from ..serializers import DeviceTokenSerializer

from utils.exceptions import error_response

logger = logging.getLogger(__name__)

class DeviceTokenRegisterView(APIView):
    """POST /api/v1/devices/register"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeviceTokenSerializer(data=request.data, context={"request":request})
        serializer.is_valid(raise_exception=True)
        token = serializer.save()
        return Response(
             {
                "success": True,
                "message": "Device token registered.",
                "data":    {"token": token.token},
            },
            status=status.HTTP_201_CREATED,
        )

class DeviceTokenDeleteView(APIView):
    """DELETE /api/v1/device/{token}"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, token):
        deleted, _ = DeviceToken.objects.filter(user=request.user, token=token).delete()
        if not deleted:
            return error_response( message="Token not found.")
        return Response({
            "success": True,
            "message": "Token deleted."
        },
        status=status.HTTP_204_NO_CONTENT
        )