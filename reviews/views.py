import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListCreateAPIView

from .serializers import ReviewListSerializer, ReviewSerializer, SubmitReviewSerializer
from .models import Review, ReviewAuditLog


from utils.permissions import IsAdmin, IsProvider
from utils.events import EventType
from notifications.publisher import publish_event

logger = logging.getLogger(__name__)


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