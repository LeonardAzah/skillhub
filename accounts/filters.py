import django_filters

from .models import ProviderProfile, KYCDocument


class ProviderFilterSet(django_filters.FilterSet):
    
    min_rating = django_filters.NumberFilter(
        field_name="average_rating", lookup_expr="gte"
    )
    min_jobs = django_filters.NumberFilter(field_name="total_jobs", lookup_expr="gte")

    class Meta:
        model = ProviderProfile
        fields = ["min_rating", "min_jobs"]

class KYCDocumentFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        choices=KYCDocument.Status.choices,
    )
    email = django_filters.CharFilter(
        field_name="user__email",
        lookup_expr="icontains",
    )
    created_at = django_filters.DateFromToRangeFilter(
        field_name="created_at",
    )
    
    class Meta:
        model = KYCDocument
        fields = ["status", "email", "created_at"]