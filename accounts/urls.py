from django.urls import path

from .views import (
       RegisterView,
       LoginView,
       LogoutView,
       MeView,TokenRefreshView,
       GoogleAuthView,
       VerifyEmailView,
       ResendVerificationView,
       OnboardingView,
 
)

urlpatterns = [
    path("/auth/register", RegisterView.as_view(), name="auth-register"),
    path("/auth/login", LoginView.as_view(), name="auth-login"),
    path("/auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("/auth/token/refresh", TokenRefreshView.as_view(), name="token-refresh"),
    path("/auth/me", MeView.as_view(), name="auth-me"),
    path("/auth/google", GoogleAuthView.as_view(), name="auth-google"),

    # Email Verification
    path("/auth/verify-email/<uuid:token>", VerifyEmailView.as_view(), name="verify-email"),
    path("/auth/resend-verification", ResendVerificationView.as_view(), name="resend-verification"),

    # Onboarding
    path("/auth/onboarding", OnboardingView.as_view(), name="onboarding"),

]