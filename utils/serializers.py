from rest_framework import serializers

class WalletPinSerializer(serializers.Serializer):
    pin = serializers.CharField(
        write_only=True,
        min_length=4,
        max_length=4,
    )

    def validate_pin(self, value: str) -> str:
        if not value.isdigit():
            raise serializers.ValidationError(
                "PIN must be exactly 4 digits."
            )

        return value