from django.urls import path

from .views import (
    ReviewView,
    ReviewDetailView,
    ProviderReviewListView,
    ProviderReviewSummaryView,
    ProviderResponseView,
    FlagReviewView,
    RemoveReviewView,
    RestoreReviewView,
    RemoveProviderResponseView,
    FlaggedReviewListView,
)


urlpatterns = [
    path(
        "",
        ReviewView.as_view(),
        name="review-list-create"
    ),

    path(
        "/flagged",
        FlaggedReviewListView.as_view(),
        name="review-flagged-list",
    ),

    path(
        "/providers/<uuid:provider_id>",
        ProviderReviewListView.as_view(),
        name="provider-review-list",
    ),

    path(
        "/providers/<uuid:provider_id>/summary",
        ProviderReviewSummaryView.as_view(),
        name="provider-reviews-summary",
    ),

    path(
        "/<uuid:pk>/response",
        ProviderResponseView.as_view(),
        name="review-response",
    ),

    path(
        "/uuid:pk>/flag",
        FlagReviewView.as_view(),
        name="reviews-flagged",
    ),

    path(
        "/<uuid:pk>/remove",
        RemoveReviewView.as_view(),
        name="review-remove"
    ),

    path(
        "/<uuid:pk>/restore",
        RestoreReviewView.as_view(),
        name="review-restore"
    ),

    path(
        "/<uuid:pk>/remove-response",
        RemoveProviderResponseView.as_view(),
        name="review-remove-response",
    ),

  path(
        "/<uuid:pk>",
        ReviewDetailView.as_view(),
        name="review-detail",
    ),
]