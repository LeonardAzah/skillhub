
import uuid
from django.core.cache import cache

from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from django_filters.rest_framework import DjangoFilterBackend

from drf_spectacular.utils import extend_schema

from utils.permissions import IsVerified

from ..models import EscrowAccount, Transaction, Payment
from ..serializers import (
    CashInInitiateSerializer,
    EscrowSerializer,
    TransactionSerializer,
    WalletSerializer,
    CashOutSerializer,
    TransactionListSerializer,
    PaymentListSerializer,
    PaymentSerializer,
    
)
from ..filters import TransactionFilter,PaymentFilter, AmountBracketFilterBackend

from ..services import initiate_cash_out, initiate_cash_in

from ._helpers import get_or_create_wallet

from utils.helpers import get_idempotency_key, _frontend_url
from django.db import transaction
from ..caching import cache, build_list_cache_key, CACHE_TTL

class CachedListMixin:
    """
    Caches the fully-paginated, fully-serialized response per user
    (or per-admin-bucket) + query string.
    """
    cache_model_name = None  # set on subclasses
    def _is_admin(self, user):
            return IsAdminUser().has_permission(self.request, self)
    
    def _cache_user_bucket(self, request):
        return "admin" if self._is_admin(request.user) else request.user.id

    def list(self, request, *args, **kwargs):
        bucket = self._cache_user_bucket(request)
        query_string = request.META.get('QUERY_STRING', '')
        cache_key = build_list_cache_key(self.cache_model_name, bucket, query_string)

        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, CACHE_TTL)
        return response
    

class WalletView(APIView):
    """
    GET /api/v1/payments/wallet
    Get authenticated user wallet balance.
    Auto-creates wallet on first access.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        wallet = get_or_create_wallet(request.user)
        return  Response(
            {
                "success": True,
                "message": f"Successfully retrieved user's wallet",
                "data":    WalletSerializer(wallet).data,
            },
            status=status.HTTP_200_OK,
        )

@extend_schema(
    request=CashInInitiateSerializer,
    responses=CashInInitiateSerializer,
)
class CashInView(APIView):
    """
    Initiate a wallet top-up.

    If the same Idempotency-Key is received more than once for the
    authenticated user, the previously created payment is returned.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        idempotency_key = get_idempotency_key(request)        
        wallet = get_or_create_wallet(request.user)
        serializer = CashInInitiateSerializer(data=request.data, context={"wallet":wallet})
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data["amount"]
        currency = serializer.validated_data["currency"]
        phone_number = serializer.validated_data["phone_number"]
        method = serializer.validated_data["method"]

        

        # Idempotency check
        payment = (
            Payment.objects
            .filter(
                user=request.user,
                idempotency_key=idempotency_key,
            )
            .first()
        )

        if payment:
            return Response(
                {
                    "success": True,
                    "message": "Existing payment found.",
                    "data": PaymentSerializer(payment).data,
                },
                status=status.HTTP_200_OK,
            )

        # Create payment
        with transaction.atomic():

            payment = initiate_cash_in(
                user=request.user, 
                wallet=wallet, 
                amount=amount,
                currency=currency,
                medium=method,
                phone_number=phone_number,
                idempotency_key=idempotency_key,
                )

        return Response(
            {
                "success": True,
                "message": "Payment initiated successfully.",
                "data": PaymentSerializer(payment).data,
            },
            status=status.HTTP_201_CREATED,
        )
    

class CashOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        idempotency_key = get_idempotency_key(request=request)

        wallet = get_or_create_wallet(request.user)

        serializer = CashOutSerializer(
            data=request.data,
            context={
                "request": request,
                "wallet": wallet,
                "idempotency_key": idempotency_key,
            },
        )

        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data["phone_number"]
        method = serializer.validated_data["method"]
        amount = serializer.validated_data["amount"]

        payment = initiate_cash_out(
            user=request.user,
            wallet=wallet,
            method=method,
            recipient_reference=phone_number,
            amount=amount,
            idempotency_key=idempotency_key,
            **serializer.validated_data,
        )

        return Response(
            {
                "success": True,
                "message": "Cash-out initiated successfully.",
                "data": PaymentSerializer(payment).data,
            },
            status=status.HTTP_201_CREATED,
        )
    


class TransactionListView(CachedListMixin, ListAPIView):
    serializer_class = TransactionListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, AmountBracketFilterBackend]
    filterset_class = TransactionFilter
    cache_model_name = "transaction"

    def get_queryset(self):
        qs = Transaction.objects.select_related('wallet', 'wallet__user', 'payment')
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(wallet__user=user)


class PaymentListView(CachedListMixin, ListAPIView):
    serializer_class = PaymentListSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, AmountBracketFilterBackend]
    filterset_class = PaymentFilter
    cache_model_name = "payment"

    def get_queryset(self):
        qs = Payment.objects.select_related('user', 'wallet')
        user = self.request.user
        if user.is_staff or user.is_superuser:
            return qs
        return qs.filter(user=user)
    


class TransactionDetailView(APIView):
    """GET /api/v1/payments/wallet/transactions/{id}/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        qs = Transaction.objects.select_related('wallet', 'wallet__user', 'payment')
        is_admin = IsAdminUser().has_permission(request, self)

        if not is_admin:
            qs = qs.filter(wallet__user=request.user)
        transaction = get_object_or_404(qs, id=pk)

        return Response(
            {"success": True, "message": "Transaction details retrieved.", "data": TransactionSerializer(transaction).data}
        )
    
class PaymentDetailView(APIView):
    """GET /api/v1/payments/{id}/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        qs = Payment.objects.select_related('user', 'wallet')
        is_admin = IsAdminUser().has_permission(request, self)

        if not is_admin:
            qs = qs.filter(user=request.user)

        payment = get_object_or_404(qs, id=pk)

        return Response(
                   {"success": True, "message": "Payment details retrieved.", "data": PaymentSerializer(payment).data}
               )
    

class EscrowDetailView(APIView):
    """GET /api/v1/payment/wallet/escrow/{appointment_id}/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, appointment_id):
        try:
            escrow = EscrowAccount.objects.get(appointment_id=appointment_id)
        except EscrowAccount.DoesNotExist:
            return Response({"error": "Escrow not found."}, status=status.HTTP_404_NOT_FOUND)

        # Only the two parties or admin may view
        user = request.user
        is_party = (
            escrow.seeker_wallet.user == user
            or escrow.provider_wallet.user == user
            or user.is_staff
        )
        if not is_party:
            return Response({"error": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        return Response(EscrowSerializer(escrow).data)
