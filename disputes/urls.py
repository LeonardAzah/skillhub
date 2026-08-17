from django.urls import path

from .views import (
    DisputeListView,
    DisputeDetailView,
    AdminDisputeDetailView,
    SubmitStatementView,
    UploadEvidenceView,
    MarkUnderReviewView,
    ResolveView,
    CloseView,
)

urlpatterns = [
    path(
        "",
        DisputeListView.as_view(),
        name="dispute-list"
    ),

    path(
        "/<uuid:pk>/statement",
        SubmitStatementView.as_view(),
        name="dispute-statement"
    ),
    path(
        "/<uuid:pk>/evidence",
        UploadEvidenceView.as_view(),
        name="dispute-evidence"
    ),
    path(
        "/<uuid:pk>",
        DisputeDetailView.as_view(),
        name="dispute-detail"
    ),
    path(
        "/all/<uuid:pk>",
        AdminDisputeDetailView.as_view(),
        name="admin-dispute-detail"
    ),
    path(
        "/<uuid:pk>/review",
        MarkUnderReviewView.as_view(),
        name="admin-dispute-review"
    ),
    path(
        "/<uuid:pk>/resolve",
        ResolveView.as_view(),
        name="admin-dispute-resolve",
    ),
    path(
        "/<uuid:pk>/close",
        CloseView.as_view(),
        name="admin-dispute-close",
    ),
]