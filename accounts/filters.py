import django_filters

from .models import ProviderProfile


class ProviderFilterSet(django_filters.FilterSet):
    

    min_rating = django_filters.NumberFilter(
        field_name="average_rating", lookup_expr="gte"
    )
    min_jobs = django_filters.NumberFilter(field_name="total_jobs", lookup_expr="gte")

    class Meta:
        model = ProviderProfile
        fields = ["min_rating", "min_jobs"]