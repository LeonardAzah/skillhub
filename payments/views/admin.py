"""
BoloConnect — apps/payments/views/admin.py
SRS §15 — Admin payment APIs

Endpoints
─────────
GET    /api/v1/admin/wallet/ledger/
POST   /api/v1/admin/wallet/{user_id}/freeze/
GET    /api/v1/admin/withdrawals/
POST   /api/v1/admin/withdrawals/{id}/approve/
POST   /api/v1/admin/withdrawals/{id}/reject/
"""
from django.db.models import Count, Q, Sum
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.permissions import IsAdmin

from ..models import Transaction, Wallet
from utils.exceptions import error_response


class FreezeWalletView(APIView):
    """
    POST /api/v1/payments/wallet/{user_id}/freeze
    POST /api/v1/payments/wallet/{user_id}/unfreeze
    Freeze/unfreeze a user wallet.
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, user_id, action="freeze"):
        # action is passed from the URL dispatcher via kwargs
        action = "unfreeze" if "unfreeze" in request.resolver_match.url_name else "freeze"
        try:
            wallet = Wallet.objects.get(user_id=user_id)
        except Wallet.DoesNotExist:
            return error_response(message="Wallet not found.", status_code=status.HTTP_404_NOT_FOUND)

        wallet.is_active = (action == "unfreeze")
        wallet.save(update_fields=["is_active"])

        return Response({
            "success":True,
            "message": f"Wallet {'frozen' if not wallet.is_active else 'unfrozen'}.",
            "data":{
                "wallet_id": str(wallet.id),
                "is_active": wallet.is_active,
            }
            
        })




