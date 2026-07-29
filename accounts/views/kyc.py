import logging


from django.utils import timezone
from rest_framework import status, generics, filters as drf_filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import  APIView
from django_filters.rest_framework import DjangoFilterBackend


from ..models import User, KYCDocument, ProviderProfile
from ..serializers import KYCSubmitSerializer, KYCDocumentSerializer, KYCDocumentDetailSerializer
from ..filters import KYCDocumentFilter

from utils.permissions import IsAdmin, IsEmailVerified
from utils.exceptions import error_response
from notifications.events import EventType
from notifications.publisher import publish_event

logger = logging.getLogger(__name__)

class KYCSubmitView(APIView):
    """Submit KYC documents"""
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def post(self, request):
        serializer = KYCSubmitSerializer(data=request.data, context={"request":request} )
        serializer.is_valid(raise_exception=True)
        doc:KYCDocument = serializer.save()

        publish_event(
            EventType.USER_KYC_SUBMITTED,
            {
                "user_id":       str(request.user.id),
                "email":         request.user.email,
                "username":      request.user.username,
                "document_type": doc.document_type,
                "document_id":   str(doc.id),
            }
        )

        return Response(
            {
                "success": True,
                "message": "Documents submitted for review. You will be notified once verified.",
                "data": {
                    "document_id": str(doc.id),
                    "status":      doc.status,
                },
            },
            status=status.HTTP_201_CREATED,
        )

class KYCStatusView(APIView):
    """Check own KYC Status"""
    permission_classes = [IsAuthenticated]
    def get(self, request):
        return Response({

            "success": True,
            "message":"KYC status retrieved.",
            "data": {
                    "is_verified": request.user.is_verified,
                    "documents": [
                        {
                            "id":               str(doc.id),
                            "document_type":    doc.document_type,
                            "document_side":    doc.document_side,
                            "status":           doc.status,
                            "rejection_reason": doc.rejection_reason,
                            "created_at":       doc.created_at.isoformat(),
                        }
                        for doc in request.user.kyc_documents.all().order_by("-created_at")
                    ],
                },
        }

        )

class KYCListView(generics.ListAPIView):
    """List all KYC documents (paginated, filterable, searchable)."""
    queryset = (
        KYCDocument.objects.select_related("user")
        .order_by("created_at")
    )
    serializer_class = KYCDocumentSerializer
    permission_classes = [IsAuthenticated, IsAdmin]

    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter]
    filterset_class = KYCDocumentFilter
    search_fields = ["user__username"]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class KYCApproveView(APIView):
    """Approve a user KYC"""
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, doc_id):
        try:
            doc = KYCDocument.objects.select_related("user").get(id=doc_id)
        except KYCDocument.DoesNotExist:
            return error_response(
                message="Document not found.",
                status=status.HTTP_404_NOT_FOUND,
            )
            

        doc.status      = KYCDocument.Status.APPROVED
        doc.reviewed_by = request.user
        doc.reviewed_at = timezone.now()
        doc.save(update_fields=["status", "reviewed_by", "reviewed_at"])

        user = doc.user
        approved_docs = user.kyc_documents.filter(status=KYCDocument.Status.APPROVED)
        has_id = approved_docs.filter(
            document_side__in=[KYCDocument.DocumentSide.FRONT, KYCDocument.DocumentSide.SINGLE]
        ).exists()

        if has_id:
            user.is_verified = True
            user.save(update_fields=["is_verified"])
            if user.role == User.Role.PROVIDER:
                try:
                    user.provider_profile.is_verified    = True
                    user.provider_profile.verified_badge = True
                    user.provider_profile.save(update_fields=["is_verified", "verified_badge"])
                except ProviderProfile.DoesNotExist:
                    return error_response(
                                    message="Provider not found.",
                                    status=status.HTTP_404_NOT_FOUND,
                                )

        publish_event(
            EventType.USER_KYC_APPROVED,
            {
                "user_id":  str(user.id),
                "email":    user.email,
                "username": user.username,
            },
        )

        return Response(
            {
                "success": True,
                "message": "Document approved.",
                "data":    {"document_id": str(doc.id)},
            }
        )

class KYCRejectView(APIView):
    """Reject kyc"""

    permission_classes = [IsAuthenticated, IsAdmin]
    def post(self, request, doc_id):
        try:
            doc = KYCDocument.objects.select_related("user").get(id=doc_id)
        except KYCDocument.DoesNotExist:
            return error_response(message="Document not found.",                 status=status.HTTP_404_NOT_FOUND,
)
        reason = request.data.get("reason", "")
        if not reason:
            return error_response(message="Rejection reason is required.", status=status.HTTP_400_BAD_REQUEST )

        doc.status = KYCDocument.Status.REJECTED
        doc.rejection_reason = reason
        doc.reviewed_by = request.user
        doc.reviewed_at = timezone.now()
        doc.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_At"])

        publish_event(
            EventType.USER_KYC_REJECTED,
            {
                "user_id":  str(doc.user.id),
                "email":    doc.user.email,
                "username": doc.user.username,
                "reason":   reason,
            }
        )

        return Response (

             {
                "success": True,
                "message": "Document rejected.",
                "data":    {"document_id": str(doc.id)},
            }


        )


class KYCDetailView(generics.RetrieveAPIView):
    """Retrieve a single KYC document by id."""
    queryset = KYCDocument.objects.select_related("user")
    serializer_class = KYCDocumentDetailSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    lookup_field = "id"
    lookup_url_kwarg = "kyc_id"

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except KYCDocument.DoesNotExist:
            return error_response(message="Document not found.",                 status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "message": "KYC document retrieved.",
                "data": serializer.data,
            }
        )