import django_filters

from .models import ProviderProfile, KYCSubmission


class ProviderFilterSet(django_filters.FilterSet):
    
    min_rating = django_filters.NumberFilter(
        field_name="average_rating", lookup_expr="gte"
    )
    min_jobs = django_filters.NumberFilter(field_name="total_jobs", lookup_expr="gte")

    class Meta:
        model = ProviderProfile
        fields = ["min_rating", "min_jobs"]

class KYCSubmissionFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        choices=KYCSubmission.Status.choices,
    )
    email = django_filters.CharFilter(
        field_name="user__email",
        lookup_expr="icontains",
    )
    nationality = django_filters.CharFilter(
        field_name="nationality",
        lookup_expr="icontains",
    )
    created_at = django_filters.DateFromToRangeFilter(
        field_name="created_at",
    )

    class Meta:
        model = KYCSubmission
        fields = ["status", "email", "nationality", "created_at"]