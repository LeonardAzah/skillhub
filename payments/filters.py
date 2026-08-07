from decimal import Decimal, InvalidOperation
from rest_framework.filters import BaseFilterBackend
from rest_framework.exceptions import ValidationError
import django_filters as df

from .models import Transaction, Payment


class AmountBracketFilterBackend(BaseFilterBackend):
    """
    Supports amount[gte]=, amount[lte]=, amount[eq]= on any view
    whose model has an `amount` field.
    """
    param_map = {
        'amount[gte]': 'amount__gte',
        'amount[lte]': 'amount__lte',
        'amount[eq]': 'amount',
    }

    def filter_queryset(self, request, queryset, view):
        filters = {}
        for raw_param, orm_lookup in self.param_map.items():
            value = request.query_params.get(raw_param)
            if value is None:
                continue
            try:
                filters[orm_lookup] = Decimal(value)
            except (InvalidOperation, TypeError):
                raise ValidationError(
                    {raw_param: f"'{value}' is not a valid decimal amount."}
                )
        return queryset.filter(**filters) if filters else queryset


class TransactionFilter(df.FilterSet):
    transaction_type = df.ChoiceFilter(choices=Transaction.Type.choices)
    wallet = df.UUIDFilter(field_name='wallet_id')
    appointment_id = df.UUIDFilter()
    created_after = df.IsoDateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = df.IsoDateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = Transaction
        fields = ['transaction_type', 'wallet', 'appointment_id']


class PaymentFilter(df.FilterSet):
    status = df.ChoiceFilter(choices=Payment.Status.choices)
    provider = df.ChoiceFilter(choices=Payment.Provider.choices)
    method = df.ChoiceFilter(choices=Payment.Method.choices)
    direction = df.ChoiceFilter(choices=Payment.Direction.choices)
    appointment_id = df.UUIDFilter()
    created_after = df.IsoDateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = df.IsoDateTimeFilter(field_name='created_at', lookup_expr='lte')

    class Meta:
        model = Payment
        fields = ['status', 'provider', 'method', 'direction', 'appointment_id']