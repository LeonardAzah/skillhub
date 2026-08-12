from django.urls import path
from .views import (
    ProviderAvailabilityView,
    ProviderAvailabilityDeleteView,
    ProviderAvailabilityBlockView,
    AppointmentListCreateView,
    AppointmentDetailView,
    AcceptAppointmentView,
    RejectAppointmentView,
    StartAppointmentView,
    CompleteAppointmentView,
    ConfirmAppointmentView,
    CancelAppointmentView,
    DisputeAppointmentView,
)

urlpatterns = [
    path(
        "", 
        AppointmentListCreateView.as_view(),name="appointment-create"
    ),
    path(
        "/<uuid:pk>/accept", 
        AcceptAppointmentView.as_view(), 
        name="appointment-accept"
        ),
    path(
        "/<uuid:pk>/start",
        StartAppointmentView.as_view(),
        name="appointment-start"
    ),
    path(
        "/<uuid:pk>/complete",
        CompleteAppointmentView.as_view(),
        name="appointment-complete",
    ),

    path(
        "/<uuid:pk>/reject",
        RejectAppointmentView.as_view(),
        name="appointment-reject"
    ),
    path(
        "/<uuid:pk>/confirm",
        ConfirmAppointmentView.as_view(),
        name="appointment-confirm",
    ),
    path(
        "/<uuid:pk>/cancel",
        CancelAppointmentView.as_view(),
        name="appointment-cancel"
    ),
    path(
        "/<uuid:pk>/dispute",
        DisputeAppointmentView.as_view(),
        name="appointment-dispute"
    ),

    path(
            "/providers/availability",
            ProviderAvailabilityBlockView.as_view(),
            name="provider-availability-block",
        ),

     path(
        "/providers/<uuid:provider_id>/availability",
        ProviderAvailabilityView.as_view(),
        name="provider-availability",
    ),
    
    path("/availability/<uuid:blocked_id>",
         ProviderAvailabilityDeleteView.as_view(),
         name="provider-availability-delete" ),

    path(
        "/<uuid:pk>",
        AppointmentDetailView.as_view(),
        name="appointment-detail"
    ),

]