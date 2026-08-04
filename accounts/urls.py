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
       ProvidersView,
       ProfileView,
       ProviderPublicProfileView,
       ProviderPortfolioListView,
       PortfolioItemCreateView,
       PortfolioItemDetailView,
       PortfolioItemTogglePublishView,
       PortfolioItemToggleFeaturedView,
       PortfolioItemImageAddView,
       PortfolioImageDetailView,
       KYCSubmitView,
       KYCApproveView,
       KYCDetailView,
       KYCListView,
       KYCRejectView,
       KYCStatusView,
       DeviceTokenRegisterView,
       DeviceTokenDeleteView,
       PasswordResetRequestView,
       PasswordResetConfirmView,
       SetNewPasswordView,
       ChangePasswordView,

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

    # Reset password
    path("/auth/password/reset",PasswordResetRequestView.as_view(), name="password-reset-request" ),
    path("/auth/password/reset/confirm/<uuid:token>", PasswordResetConfirmView.as_view(), name="password-reset-confirm"  ),
    path("/auth/password/reset/confirm", SetNewPasswordView.as_view(), name="password-reset-set"),
    path("/auth/password/change", ChangePasswordView.as_view(), name="password-change"),

    # Onboarding
    path("/auth/onboarding", OnboardingView.as_view(), name="onboarding"),

    #profile

    path("/profile/providers", ProvidersView.as_view(), name='providers'),
    path("/profile", ProfileView.as_view(), name="profile"),
    path("/profile/provider/<uuid:provider_id>", ProviderPublicProfileView.as_view(), name="provider-public-profile"),

    #portfolio

    path("/portfolio/provider/<uuid:provider_id>", ProviderPortfolioListView.as_view(), name="provider-portfolio-list"),
    path("/portfolio", PortfolioItemCreateView.as_view(), name="portfolio-create"),
    path("/portfolio/<uuid:item_id>", PortfolioItemDetailView.as_view(), name="portfolio-detail"),
    path("/portfolio/<uuid:item_id>/toggle-publish", PortfolioItemTogglePublishView.as_view(), name="portfolio-toggle-publish"),
    path("/portfolio/<uuid:item_id>/toggle-featured", PortfolioItemToggleFeaturedView.as_view(), name="portfolio-toggle-featured"),

    path("/portfolio/<uuid:item_id>/images", PortfolioItemImageAddView.as_view(), name="portfolio-image-add"),
    path("/portfolio/images/<uuid:image_id>", PortfolioImageDetailView.as_view(), name="portfolio-image-detail"),

    #KYC
    path("/profile/verify", KYCSubmitView.as_view(), name="kyc-submit"),
    path("/profile/verify/status", KYCStatusView.as_view(), name="kyc-status"),
    path("/kyc", KYCListView.as_view(), name="admin-kyc-list"),
    path("/kyc/<uuid:doc_id>/approve", KYCApproveView.as_view(), name="kyc-approve"),
    path("/kyc/<uuid:doc_id>/reject", KYCRejectView.as_view(), name="kyc-reject"),
    path("/kyc/<uuid:kyc_id>", KYCDetailView.as_view(), name="admin-kyc-detail"),


    #Device tokens
    path("/devices/register", DeviceTokenRegisterView.as_view(), name='device-register'),
    path("/devices/<str:token>",DeviceTokenDeleteView.as_view(), name='device-delete')

]