from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.events import EventType
from notifications.publisher import publish_event

from ..constants import WALLET_PIN_TOKEN_BOOKING, WALLET_PIN_TOKEN_WITHDRAWAL
from ..serializers import SetWalletPinSerializer, VerifyWalletPinSerializer


class SetWalletPinView(APIView):
    """
    POST /api/v1/payments/wallet/pin
    Set or change the 4-digit wallet PIN.

    First use (no existing PIN): { new_pin, confirm_pin }
    Change (PIN already set):    { current_pin, new_pin, confirm_pin }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SetWalletPinSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        publish_event(EventType.WALLET_PIN_SET, {
            "user_id": str(request.user.id),
            "email":   request.user.email,
        })

        return Response(
            {"success": True,
             "message": "Wallet PIN set successfully.",
            "data":{}
             },
            status=status.HTTP_200_OK,
        )


class VerifyWalletPinView(APIView):
    """
    POST /api/v1/wallet/pin/verify/
    Verify the wallet PIN and issue short-lived authorisation tokens.

    Body: { pin, purpose }
    purpose: "booking" | "withdrawal" | "all"  (default: "all")

    On success stores:
      wallet_pin_verified:{seeker_id}     TTL = 5 min  (for booking)
      wallet_pin_withdrawal:{user_id}     TTL = 5 min  (for withdrawal)

    These tokens are single-use — consumed by the operation that requires them.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = VerifyWalletPinSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        tokens = serializer.save()

        publish_event(EventType.WALLET_PIN_VERIFIED, {
            "user_id": str(request.user.id),
            "purpose": request.data.get("purpose", "all"),
        })

        return Response(
            {
                "success":True,
                "message": "PIN verified successfully.",
                **tokens,
                "data":{}
            },
            status=status.HTTP_200_OK,
        )


class WalletPinStatusView(APIView):
    """
    GET /api/v1/wallet/pin/status
    Returns PIN status and active token flags.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user   = request.user
        has_pin= hasattr(user, "wallet_pin") and user.wallet_pin.is_set

        data = {
            "is_set":        has_pin,
            "is_locked":     False,
            "locked_until":  None,
            "booking_token_active":    False,
        }

        if has_pin:
            pin = user.wallet_pin
            data["is_locked"]    = pin.is_locked
            data["locked_until"] = pin.locked_until.isoformat() if pin.locked_until else None

        # Check booking token (uses seeker_profile id)
        if hasattr(user, "seeker_profile"):
            data["booking_token_active"] = bool(
                cache.get(f"{WALLET_PIN_TOKEN_BOOKING}:{user.seeker_profile.id}")
            )

        return Response(
                    {
                        "success":True,
                        "message": "Successfully retrive status.",
                        "data":data,

                    },
                    status=status.HTTP_200_OK,
                )
