from django.urls import path
from .views import (
    ProviderAvailabilityView,
    ProviderAvailabilityDeleteView,
    ProviderAvailabilityBlockView,
    AppointmentListCreateView,
    AppointmentDetailView,
)

urlpatterns = [
    path(
        "", AppointmentListCreateView.as_view(),name="appointment-create"
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