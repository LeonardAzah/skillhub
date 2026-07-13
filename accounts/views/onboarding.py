"""
Post-email-verification role selection.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import User
from ..serializers import OnboardingSerializer, UserSummarySerializer


class OnboardingView(APIView):
    """
    POST /api/v1/auth/onboarding/
    Post-verification role selection.
    No external event needed; role is surfaced on the JWT claims on next login.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.has_completed_onboarding:
            return Response(
                {
                    "success": False,
                    "message": "Onboarding already completed.",
                    "errors":  {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = OnboardingSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user: User = serializer.save()

        return Response(
            {
                "success": True,
                "message": f"Onboarding complete. Welcome as a {user.get_account_type_display()}!",
                "data":    {"user": UserSummarySerializer(user).data},
            },
            status=status.HTTP_200_OK,
        )
