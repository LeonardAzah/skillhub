from decimal import Decimal
from rest_framework import serializers
from decimal import ROUND_HALF_UP

VALID_INCREMENTS = {
    Decimal("1.0"), Decimal("1.5"), Decimal("2.0"), Decimal("2.5"),
    Decimal("3.0"), Decimal("3.5"), Decimal("4.0"), Decimal("4.5"),
    Decimal("5.0"),
}

def _validate_half_step(v):
    """Ratings must be in 0.5 increments: 1.0 , 1.5, ..., 5.0"""
    from django.core.exceptions import ValidationError
    value = Decimal(str(v))
    if value < Decimal("1.0") or value > Decimal("5.0"):
        raise ValidationError("Rating must be between 1.0 and 5.0")
    remainder = (value * 2) % 1
    if remainder != 0:
        raise ValidationError("Rating must be in 0.5 increments (e.g. 1.0, 1.5, ... 5.0).")


def _validate_rating(v) -> Decimal:
    value = Decimal(str(v))

    if value not in VALID_INCREMENTS:
        raise serializers.ValidationError(
            "Rating must be between 1.0 and 5.0 in 0.5 increments "
            "(e.g. 1.0, 1.5, 2.0 … 5.0)."
        )

    return value

def _round2(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

