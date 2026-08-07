import logging

from django.utils import timezone
from rest_framework import status, generics, filters as drf_filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from ..models import User, KYCSubmission, ProviderProfile
from ..serializers import (
    KYCSubmissionCreateSerializer,
    KYCSubmissionListSerializer,
    KYCSubmissionDetailSerializer,
    KYCStatusSerializer,
)
from ..filters import KYCSubmissionFilter

from utils.permissions import IsAdmin, IsEmailVerified
from utils.exceptions import error_response
from notifications.events import EventType
from notifications.publisher import publish_event

from drf_spectacular.utils import extend_schema


logger = logging.getLogger(__name__)


@extend_schema(
    request=KYCSubmissionCreateSerializer,
    responses=KYCSubmissionCreateSerializer,
)
class KYCSubmitView(APIView):
    """Submit (or re-submit, after a rejection) a full KYC application."""

    permission_classes = [IsAuthenticated, IsEmailVerified]

    def post(self, request):
        serializer = KYCSubmissionCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        submission: KYCSubmission = serializer.save()

        publish_event(
            EventType.USER_KYC_SUBMITTED,
            {
                "user_id":       str(request.user.id),
                "email":         request.user.email,
                "username":      request.user.username,
                "submission_id": str(submission.id),
            },
        )

        return Response(
            {
                "success": True,
                "message": "KYC submitted for review. You will be notified once verified.",
                "data": {
                    "submission_id": str(submission.id),
                    "status":        submission.status,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class KYCStatusView(APIView):
    """Check own KYC status (latest submission, with its documents)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = KYCStatusSerializer(request.user, context={"request": request})
        return Response(
            {
                "success": True,
                "message": "KYC status retrieved.",
                "data": serializer.data,
            }
        )


class KYCListView(generics.ListAPIView):
    """List all KYC submissions (paginated, filterable, searchable) — admin review queue."""

    queryset = KYCSubmission.objects.select_related("user").order_by("created_at")
    serializer_class = KYCSubmissionListSerializer
    permission_classes = [IsAuthenticated, IsAdmin]

    filter_backends = [DjangoFilterBackend, drf_filters.SearchFilter]
    filterset_class = KYCSubmissionFilter
    search_fields = ["user__username", "full_name"]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class KYCApproveView(APIView):
    """Approve a user's KYC submission."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, kyc_id):
        try:
            submission = KYCSubmission.objects.select_related("user").get(id=kyc_id)
        except KYCSubmission.DoesNotExist:
            return error_response(
                message="Submission not found.",
                status=status.HTTP_404_NOT_FOUND,
            )

        submission.status      = KYCSubmission.Status.APPROVED
        submission.reviewed_by = request.user
        submission.reviewed_at = timezone.now()
        submission.save(update_fields=["status", "reviewed_by", "reviewed_at"])

        # Required documents (ID doc + selfie + location plan) are already
        # guaranteed present at submission time, so approving the
        # submission is enough to mark the user verified — no more
        # per-document bookkeeping needed here.
        user = submission.user
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
                "message": "KYC submission approved.",
                "data":    {"submission_id": str(submission.id)},
            }
        )


class KYCRejectView(APIView):
    """Reject a user's KYC submission."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, kyc_id):
        try:
            submission = KYCSubmission.objects.select_related("user").get(id=kyc_id)
        except KYCSubmission.DoesNotExist:
            return error_response(
                message="Submission not found.",
                status=status.HTTP_404_NOT_FOUND,
            )

        reason = request.data.get("reason", "")
        if not reason:
            return error_response(
                message="Rejection reason is required.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        submission.status            = KYCSubmission.Status.REJECTED
        submission.rejection_reason  = reason
        submission.reviewed_by       = request.user
        submission.reviewed_at       = timezone.now()
        submission.save(
            update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at"]
        )

        publish_event(
            EventType.USER_KYC_REJECTED,
            {
                "user_id":  str(submission.user.id),
                "email":    submission.user.email,
                "username": submission.user.username,
                "reason":   reason,
            },
        )

        return Response(
            {
                "success": True,
                "message": "KYC submission rejected.",
                "data":    {"submission_id": str(submission.id)},
            }
        )


class KYCDetailView(generics.RetrieveAPIView):
    """Retrieve a single KYC submission (with documents) by id."""

    queryset = KYCSubmission.objects.select_related("user").prefetch_related("documents")
    serializer_class = KYCSubmissionDetailSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    lookup_field = "id"
    lookup_url_kwarg = "kyc_id"

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
        except KYCSubmission.DoesNotExist:
            return error_response(
                message="Submission not found.",
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "message": "KYC submission retrieved.",
                "data": serializer.data,
            }
        )