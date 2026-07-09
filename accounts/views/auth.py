from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView as BaseTokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken

from ..models import User, EmailVerificationToken, DeviceToken
from ..serializers import (RegisterSerializer, UserSummarySerializer, LogoutSerializer, GoogleAuthSerializer)

class RegisterView(APIView):
    """
    POST /api/v1/auth/register
    Create account
    """
    permission_classes = [AllowAny]
    throttle_scope = 'anon'

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user: User = serializer.save()

        return Response(
            {
                "success": True,
                "message": "Account created successfully. Please check your email to verify your account.",
                "data":    {"user": UserSummarySerializer(user).data},
            },
            status=status.HTTP_201_CREATED,
        )

class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login
    Login user and return JWT tokens
    """
    permission_classes = [AllowAny]
    throttle_scope = 'login'


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    SRS §4.3 — Blacklist refresh token, deactivate device token.
    No domain event needed (logout is a session concern, not a domain concern).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        token_value = request.data.get("device_token")
        if token_value:
            DeviceToken.objects.filter(user=request.user, token=token_value).update(is_active=False)

        return Response(
            {"success": True, "message": "Logged out successfully.", "data": {}},
            status=status.HTTP_200_OK,
        )

class TokenRefreshView(BaseTokenRefreshView):
    """
    POST /api/v1/auth/token/refresh/
    Rotates refresh token.  No domain event needed.
    """
    permission_classes = [AllowAny]
    

class MeView(APIView):
    """GET /api/v1/auth/me/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "success": True,
                "message": "User retrieved.",
                "data":    UserSummarySerializer(request.user).data,
            }
        )
    
class GoogleAuthView(APIView):
    """
    POST /api/v1/auth/google/
    Google OAuth token exchange.
    Auto-creates account if first sign-in.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user: User = serializer.validated_data['user']
        created: bool = serializer.validated_data["created"]

        if not user.is_active:
            return Response(
                {
                    "success": False,
                    "message": "This account has been deactivated.",
                    "errors":  {},
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = RefreshToken.for_user(user)
        refresh["user_id"]      = str(user.id)
        refresh["role"]         = user.role or ""
        refresh["is_verified"]  = user.is_verified
        refresh["account_type"] = user.account_type or ""

        return Response(
            {
                "success": True,
                "message": (
                    "Account created via Google. Please complete onboarding to select your role."
                    if created else
                    "Logged in successfully."
                ),
                "data": {
                    "access":          str(refresh.access_token),
                    "refresh":         str(refresh),
                    "user":            UserSummarySerializer(user).data,
                    "account_created": created,
                },
            },
            status=status.HTTP_200_OK,
        )