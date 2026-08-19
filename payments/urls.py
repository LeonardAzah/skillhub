from django.urls import path

from .views import (
    FreezeWalletView,
    CashInView,
    CashOutView,
    EscrowDetailView,
    PaymentWebhookView,
    SetWalletPinView,
    TransactionDetailView,
    PaymentDetailView,
    TransactionListView,
    VerifyWalletPinView,
    WalletPinStatusView,
    WalletView,
    PaymentListView,
    
)

urlpatterns = [
path("", PaymentListView.as_view(), name="payment-list"),

path("/wallet", WalletView.as_view(), name="wallet-detail"),

path("/wallet/cashin", CashInView.as_view(), name="wallet-cashin"),

path("/wallet/cashout", CashOutView.as_view(), name="wallet-cashout"),

path("/wallet/transactions", TransactionListView.as_view(), name="transaction-list"),

path("/wallet/transactions/<uuid:pk>", TransactionDetailView.as_view(), name="transaction-detail"),

path("/webhook", PaymentWebhookView.as_view(), name="payment-webhook"),

path("/wallet/escrow/<uuid:appointment_id>", EscrowDetailView.as_view(), name="escrow-detail"),
path("/wallet/<uuid:user_id>/freeze",FreezeWalletView.as_view(), name="wallet-freeze"),
path("/wallet/<uuid:user_id>/unfreeze/", FreezeWalletView.as_view(), name="admin-wallet-unfreeze"),


path("/wallet/pin",SetWalletPinView.as_view(), name="wallet-pin-set"),
path("/wallet/pin/verify", VerifyWalletPinView.as_view(), name="wallet-pin-verify"),
path("/wallet/pin/status", WalletPinStatusView.as_view(), name="wallet-pin-status"),

path("/<uuid:pk>", PaymentDetailView.as_view(), name="payment-detail"),
]