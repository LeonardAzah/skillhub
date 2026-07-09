from rest_framework import serializers
from ..models import User


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "role",
            "account_type",
            "is_email_verified",
            "is_verified",
            "has_completed_onboarding",
            "profile_picture"
        ]
        read_only_fields = [
            "id",
            "email",
            "username",
            "role",
            "account_type",
            "is_email_verified",
            "is_verified",
            "has_completed_onboarding",
        ]