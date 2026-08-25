import logging
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView, ListAPIView

from .serializers import (
    ReviewListSerializer, 
    ReviewSerializer, 
    SubmitReviewSerializer, 
    EditReviewSerializer, 
    ProviderReviewSummarySerializer, 
    ProviderResponseSerializer, 
    FlagReviewSerializer,
    RemoveReviewSerializer,
    )
from .models import Review, ReviewAuditLog, ProviderReviewSummary


from utils.permissions import IsAdmin, IsProvider
from accounts.models import ProviderProfile
from utils.events import EventType
from notifications.publisher import publish_event
from utils.exceptions import error_response

logger = logging.getLogger(__name__)


SORT_MAP = {
    "highest": ("-overall_rating", "-created_at"),
    "lowest": ("overall_rating", "-created_at"),
    "recent": ("-created_at",),
}

def _enqueue_recalc(provider_id:str) -> None:
    """Fire-and-forget recalculation task-never blocks the requests."""
    from .tasks import recalculate_provider_rating
    try:
        recalculate_provider_rating.apply_async(
            kwargs = {
                "provider_id": str(provider_id)
            },
            queue="default",
            countdown=2
        )
    except Exception as exc:
        logger.error(
           "Failed to enqueue rating recalculation",
            extra={"provider_id": str(provider_id), "error": str(exc)}, 
        )


class ReviewView(ListCreateAPIView):
    """
    GET  /api/v1/reviews - seeker's own review history.
    POST /api/v1/reviews - submit a review (seeker only).

    Emits: reviews.review.created
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return SubmitReviewSerializer
        return ReviewListSerializer

    def get_queryset(self):
        return Review.objects.filter(
            reviewer=self.request.user
        ).select_related("provider__user").order_by("-created_at")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review: Review = serializer.save()

        # Async rating recalculation
        _enqueue_recalc(str(review.provider.id))

        publish_event(EventType.REVIEW_CREATED, {
            "review_id": str(review.id),
            "appointment_id": str(review.appointment.id),
            "provider_id": str(review.provider.id),
            "reviewer_id": str(review.reviewer.id),
            "overall_rating": str(review.overall_rating),
            "communication": str(review.communication_rating),
            "punctuality": str(review.punctuality_rating),
            "quality": str(review.quality_rating),
            "has_comment": bool(review.comment),
        })

        # Response uses ReviewSerializer, not SubmitReviewSerializer/ReviewListSerializer
        output = ReviewSerializer(review, context=self.get_serializer_context())

        return Response(
            {
                "success": True,
                "message":"Appointment review submitted successfully.",
                "data": output.data,
            },

        status=status.HTTP_201_CREATED
        )

class ReviewDetailView(RetrieveUpdateAPIView):
    """
    GET   /api/v1/reviews/{id}
    PATCH /api/v1/reviews/{id}
    Seeker may edit within 24h of submission.
    """
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "head", "options"] 

    queryset = Review.objects.select_related(
        "reviewer", "provider__user", "appointment"
    )

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return EditReviewSerializer
        return ReviewSerializer

    def get_object(self):
        try:
            return self.get_queryset().get(pk=self.kwargs["pk"])
        except Review.DoesNotExist:
            return error_response(
                message="Review not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

    def retrieve(self, request, *args, **kwargs):
        review = self.get_object()
        if not review.is_visible and not request.user.is_staff:
            return error_response(
                message="Review not found.",
                status_code=status.HTTP_404_NOT_FOUND
            )
        return Response({
            "success":True,
            "message":"Review retrived successfully.",
            "data": ReviewSerializer(review).data,
        },
        status=status.HTTP_200_OK
           )

    def partial_update(self, request, *args, **kwargs):
        review = self.get_object()

        if review.reviewer != request.user:
            return error_response(
                message="Forbidden.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        
        serializer = self.get_serializer(data=request.data, context={"review": review})
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        _enqueue_recalc(str(review.provider.id))

        publish_event(EventType.REVIEW_EDITED, {
            "review_id": str(review.id),
            "provider_id": str(review.provider.id),
            "reviewer_id": str(review.reviewer.id),
            "overall_rating": str(review.overall_rating),
        })

        return Response(

                {
                    "success":True,
                    "message":"Review updated successfully.",
                    "data":ReviewSerializer(review).data,
                },
                status=status.HTTP_200_OK
            )

class ProviderReviewListView(ListAPIView):
    """
    GET /api/v1/reviews/providers/{id}
    Paginated public review list for a provider.

    Query params:
      sort — recent (default) | highest | lowest
      page — 1-based
    """
    serializer_class = ReviewListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        provider_id = self.kwargs["provider_id"]
        ordering = SORT_MAP.get(self.request.query_params.get("sort"), SORT_MAP["recent"])

        return Review.objects.filter(
            provider_id=provider_id, is_visible=True
        ).select_related("reviewer").order_by(*ordering)

    def list(self, request, *args, **kwargs):
        provider_id = self.kwargs["provider_id"]
        if not ProviderProfile.objects.filter(id=provider_id).exists():
            return error_response(
                message="Provider not found.",
                status_code=status.HTTP_404_NOT_FOUND
            )
        return super().list(request, *args, **kwargs)

class ProviderReviewSummaryView(APIView):
    """GET /api/v1/reviews/providers/{id}/summary"""
    permission_classes = [AllowAny]

    def get(self, request, provider_id):
        try:
            provider = ProviderProfile.objects.get(id=provider_id)
        except ProviderProfile.DoesNotExist:
            return error_response(
                message="Provider not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        try:
            summary = provider.review_summary
        except ProviderReviewSummary.DoesNotExist:
            return Response({
                "total_reviews": 0,
                "avg_communication": 0.00,
                "avg_punctuality": 0.00,
                "avg_quality": 0.00,
                "avg_overall": 0.00,
                "star_distribution": {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0},
                "top_rated": False,
                "public_rating_visible": False,
                "last_updated": None,
            })
        return Response({
            "success":True,
            "mesage":"Successfully retrived provider review summary.",
            "data":ProviderReviewSummarySerializer(summary).data,
        }, status=status.HTTP_200_OK)

class ProviderResponseView(APIView):
    """
    POST /api/v1/reviews/{id}/response
    Provider submits on public response within 30 days.

    Emits: reviews.review.response_added
    """

    permission_classes = [IsAuthenticated, IsProvider]

    def post(self, request, pk):
        try:
            review = Review.objects.select_related(
                "provider__user", "rreviewe"
            ).get(id=pk)
        except Review.DoesNotExist:
            return error_response(
                message="Review not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if review.provider.user != request.user:
            return error_response(
                message="Forbidden.",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        serializer = ProviderResponseSerializer(
            data=request.data,
            context={"review":review},
            )
        
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        publish_event(EventType.REVIEW_RESPONSE_ADDED, {
            "review_id": str(review.id),
            "provider_id": str(review.provider.id),
            "reviewer_id": str(review.reviewer.id),
            "response_text": review.provider_response
        })

        return Response({
            "success": True,
            "message":"Successfully submit response to review",
            "data": ReviewSerializer(review).data
        },
        status=status.HTTP_200_OK
        )

class FlagReviewView(APIView):
    """
    POST /api/v1/reviews/{id}/flag
    Flag a review for moderation.

    Emits: reviews.review.flagged
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        try:
            review = Review.objects.select_related("provider", "reviewer").get(id=pk)
        except Review.DoesNotExist:
            return error_response(
                message="Review not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        serializer = FlagReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data["reason"]

        old_flagged = review.is_flagged
        review.is_flagged = True
        review.flag_reason = reason
        review.save(update_fields=["is_flagged", "flag_reason", "updated_at"])

        ReviewAuditLog.objects.create(
            review = review,
            review_id_snapshot = review.id,
            action = ReviewAuditLog.Action.FLAGGED,
            actor = request.user,
            reason = reason,
            diff = {"is_flagged": [old_flagged, True]},
        )

        publish_event(EventType.REVIEW_FLAGGED, {
            "review_id": str(review.id),
            "provider_id": str(review.provider.id),
            "reviewer_id": str(review.reviewer.id),
            "reason": reason,
        })

        return Response({
            "success":True,
            "message": "Successfully flaged the review",
            "data": ReviewSerializer(review).data,
        }, status=status.HTTP_200_OK)


class RemoveReviewView(APIView):
    """
    POST /api/v1/reviews/{id}/remove
    Remove review from public view

    Emits: reviews.review.removed
    Triggers: recalculation (removed reviews excluded from summary)
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        try:
            review = Review.objects.select_related("provider", "reviewer").get(id=pk)
        except Review.DoesNotExist:
            return error_response(
                message="Review not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = RemoveReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data["reason"]

        was_visible = review.is_visible
        review.is_visible = False
        review.is_flagged = True
        review.flag_reason = reason
        review.save(update_fields=["is_visible", "is_flagged", "flag_reason", "updated_at"])

        ReviewAuditLog.objects.create(
            review = review,
            review_id_snapshot = review.id,
            action = ReviewAuditLog.Action.REMOVED,
            actor = request.user,
            reason = reason,
            diff = {"is_visible": [was_visible, False]},
        )

        _enqueue_recalc(str(review.provider.id))

        publish_event(EventType.REVIEW_REMOVED,{
            "review_id": str(review.id),
            "provider_id": str(review.provider.id),
            "reviewer_id": str(review.reviewer.id),
            "reason": reason,
        })

        return Response({
            "success":True,
            "message":"Review removed from view.",
            "data":ReviewSerializer(review).data,
        }, status=status.HTTP_200_OK)


class RestoreReviewView(APIView):
    """
    POST /api/v1/reviews/{id}/restore
    Restore a previously removed review.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request, pk):
        try:
            review = Review.objects.select_related("provider", "reviewer").get(id=pk)
        except Review.DoesNotExist:
            return error_response(
                message="Review not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        was_visible = review.is_visible
        review.is_visible = True
        review.is_flagged = False
        review.save(update_fields=["is_visible", "is_flagged", "updated_at"])

        ReviewAuditLog.objects.create(
            review = review,
            review_id_snapshot = review.id,
            action = ReviewAuditLog.Action.RESTORED,
            actor = request.user,
            diff = {"is_visible": [was_visible, True]},
        )

        _enqueue_recalc(str(review.provider.id))

        return Response({
            "success": True,
            "message": "Review was restored successfully.",
            "data": ReviewSerializer(review).data,
        }, status=status.HTTP_200_OK)


class RemoveProviderResponseView(APIView):
    """
    POST /api/v1/reviews/{id}/remove-response
    Remove a provider's public response.
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    def post(Self, request, pk):
        try:
            review = Review.objects.select_related("provider").get(id=pk)
        except Review.DoesNotExist:
            return error_response(
                message="Review not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not review.provider_response:
            return error_response(
                message="This review has no provider response.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        ReviewAuditLog.objects.create(
            review = review,
            review_id_snapshot = review.id,
            action = ReviewAuditLog.Action.RESPONSE_REMOVED,
            actor = request.user,
            diff = {"provider_response": [review.provider_response[:50], ""]},
        )

        review.provider_response = ""
        review.provider_response_at = None
        review.save(update_fields=["provider_response", "provider_response_at", "updated_at"])

        return Response(
            {
                "success":True,
                "message":"Provider's response has been removed successfully.",
                "data": ReviewSerializer(review).data,
            },
            status=status.HTTP_200_OK
        )

class FlaggedReviewListView(ListAPIView):
    """
    GET /api/v1/reviews/flagged
    List all flagged reviews.
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = ReviewSerializer

    queryset = Review.objects.filter(
        is_flagged=True
    ).select_related(
        "provider__user", "reviewer", "appointment"
    ).order_by("-updated_at")
    