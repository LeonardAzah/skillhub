import django_filters as df
from .models import Dispute


class DisputeFilter(df.FilterSet):
    status = df.CharFilter(field_name="status")
    resolution = df.CharFilter(field_name="resolution")
    appointment_id = df.UUIDFilter(field_name="appointment_id")

    class Meta:
        model = Dispute
        fields = ["status", "resolution", "appointment_id"]