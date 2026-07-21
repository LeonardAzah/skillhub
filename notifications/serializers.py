from rest_framework import serializers, status
from .models import Notification, NotificationPreference, EmailLog


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Notification
        fields = [
            "id", "notification_type", "title", "body", "data",
            "is_read", "event_type", "created_at",
        ]
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model  = NotificationPreference
        fields = ["notification_type", "push_enabled", "email_enabled", "updated_at"]


class UpdatePreferenceSerializer(serializers.Serializer):
    """PATCH body — list of preference updates."""
    preferences = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
    )

    def validate_preferences(self, value):
        valid_types = {c[0] for c in Notification.NotificationType.choices}
        for item in value:
            if "notification_type" not in item:
                raise serializers.ValidationError("Each item must include 'notification_type'.")
            if item["notification_type"] not in valid_types:
                raise serializers.ValidationError(
                    f"Unknown notification_type: {item['notification_type']}"
                )
        return value

    def save(self):
        user = self.context["request"].user
        updated = []
        for item in self.validated_data["preferences"]:
            pref, _ = NotificationPreference.objects.get_or_create(
                user=user,
                notification_type=item["notification_type"],
            )
            if "push_enabled" in item:
                pref.push_enabled = bool(item["push_enabled"])
            if "email_enabled" in item:
                pref.email_enabled = bool(item["email_enabled"])
            pref.save()
            updated.append(pref)
        return updated
