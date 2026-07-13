from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import User, SeekerProfile, ProviderProfile
from ..serializers import (
    SeekerProfileSerializer,
    UpdateSeekerProfileSerializer,
    ProviderProfileSerializer,
    UpdateProviderProfileSerializer,
)



# Maps account_type -> (related_name on User, read serializer, write serializer)
PROFILE_CONFIG = {
    User.AccountType.SEEKER: {
        "related_name": "seeker_profile",
        "model": SeekerProfile,
        "read_serializer": SeekerProfileSerializer,
        "write_serializer": UpdateSeekerProfileSerializer,
    },
    User.AccountType.PROVIDER: {
        "related_name": "provider_profile",
        "model": ProviderProfile,
        "read_serializer": ProviderProfileSerializer,
        "write_serializer": UpdateProviderProfileSerializer,
    },
}


class ProfileView(APIView):
    """
    GET   /api/v1/profile/
    PATCH /api/v1/profile/
    """
    permission_classes = [IsAuthenticated]

    def _get_config(self, request):
        """Returns (config, profile) or (None, None) with an error Response set on self._error."""
        self._error = None
        account_type = request.user.account_type

        if not account_type:
            self._error = Response(
                {
                    "success": False,
                    "message": "Please complete onboarding before accessing a profile.",
                    "errors": {},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
            return None, None

        config = PROFILE_CONFIG.get(account_type)
        if config is None:
            # Defensive: shouldn't happen given the AccountType choices, but guards
            # against future account types being added without a matching entry here.
            self._error = Response(
                {"success": False, "message": "Unsupported account type.", "errors": {}},
                status=status.HTTP_400_BAD_REQUEST,
            )
            return None, None

        try:
            profile = getattr(request.user, config["related_name"])
        except config["model"].DoesNotExist:
            self._error = Response(
                {
                    "success": False,
                    "message": "Profile not found. Please complete onboarding.",
                    "errors": {},
                },
                status=status.HTTP_404_NOT_FOUND,
            )
            return None, None

        return config, profile

    def get(self, request):
        config, profile = self._get_config(request)
        if config is None:
            return self._error

        data = config["read_serializer"](profile).data
        return Response({"success": True, "message": "Profile retrieved.", "data": data})

    def patch(self, request):
        config, profile = self._get_config(request)
        if config is None:
            return self._error

        serializer = config["write_serializer"](profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        data = config["read_serializer"](profile).data
        return Response({"success": True, "message": "Profile updated.", "data": data}, status=status.HTTP_200_OK)


class ProviderPublicProfileView(APIView):
    """
    GET /api/v1/profile/provider/{id}/
    Public read of a *specific* provider by ID
    """
    permission_classes = [AllowAny]

    def get(self, request, provider_id):
        try:
            profile = ProviderProfile.objects.select_related("user").get(id=provider_id)
        except ProviderProfile.DoesNotExist:
            return Response(
                {"success": False, "message": "Provider not found.", "errors": {}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {"success": True, "message": "Provider profile retrieved.", "data": ProviderProfileSerializer(profile).data}
        )