import re

from rest_framework import serializers

from ..models import (
    User,
    SeekerProfile,
    ProviderProfile,
)

from .portfolio import PortfolioItemSerializer

# Seeker Profile

class SeekerProfileSerializer(serializers.ModelSerializer):
    """
    Seeker profile read/update.
    """
    email = serializers.EmailField(source="user.email", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    is_verified = serializers.BooleanField(source="user.is_verified", read_only=True)
    account_type = serializers.CharField(source="user.account_type", read_only=True)
    profile_picture = serializers.URLField(source="user.profile_picture")
    is_kyc_verified = serializers.BooleanField(source="user.is_verified", read_only=True)


    class Meta:
        model = SeekerProfile
        fields = [
            "id",
            "email",
            "username",
            "phone_number",
            "full_name",
            "bio",
            "profile_picture",
            "preferred_location_lat",
            "preferred_location_lng",
            "is_verified",
            "is_kyc_verified",
            "account_type",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "email", "username", "phone_number", "is_verified", "account_type", "created_at", "updated_at", "is_kyc_verified"]


class UpdateSeekerProfileSerializer(serializers.ModelSerializer):
    """PATCH — mutable seeker profile fields."""
    # Allow updating phone on the user model
    phone_number = serializers.CharField(source="user.phone_number", required=False)
    full_name = serializers.CharField(required=False, allow_blank=True)
    profile_picture = serializers.URLField(source="user.profile_picture")

    class Meta:
        model = SeekerProfile
        fields = [
            "full_name",
            "bio",
            "profile_picture",
            "preferred_location_lat",
            "preferred_location_lng",
            "phone_number",
        ]

    def validate_phone_number(self, value):
        if value and not re.match(r"^\+\d{7,15}$", value):
            raise serializers.ValidationError("Phone must be E.164 format.")
        user = self.instance.user
        if User.objects.filter(phone_number=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Phone number already in use.")
        return value

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        user = instance.user
        if "phone_number" in user_data:
            instance.user.phone_number = user_data["phone_number"]
            instance.user.save(update_fields=["phone_number"])
        if "profile_picture" in user_data:
            user.profile_picture = user_data["profile_picture"]
        
        if user_data:
            user.save()
        
        return super().update(instance, validated_data)


# Provider Profile

class ProviderProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    is_kyc_verified = serializers.BooleanField(source="user.is_verified", read_only=True)
    profile_picture = serializers.URLField(source="user.profile_picture")
    portfolio_items = serializers.SerializerMethodField()

    class Meta:
        model = ProviderProfile
        fields = [
            "id",
            "email",
            "username",
            "phone_number",
            "full_name",
            "bio",
            "profile_picture",
            "hourly_rate",
            "experience_years",
            "service_radius_km",
            "location_lat",
            "location_lng",
            "location_address",
            "is_verified",
            "verified_badge",
            "average_rating",
            "total_jobs",
            "is_kyc_verified",
            "portfolio_items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "email", "username", "phone_number",
            "is_verified", "verified_badge", "average_rating",
            "total_jobs", "is_kyc_verified", "created_at", "updated_at",
        ]

    def get_portfolio_items(self, obj):
        """
        Public viewers (and other users) only see published items.
        The owning provider viewing their own profile also sees drafts —
        controlled via `is_owner` passed in serializer context.
        """
        request = self.context.get("request")
        is_owner = bool(
            request
            and request.user.is_authenticated
            and getattr(request.user, "role", None) == "provider"
            and hasattr(request.user, "provider_profile")
            and request.user.provider_profile.id == obj.id
        )

        queryset = obj.portfolio_items.prefetch_related("images")
        if not is_owner:
            queryset = queryset.filter(is_published=True)
        queryset = queryset.order_by("display_order", "-completed_on", "-created_at")

        return PortfolioItemSerializer(queryset, many=True, context=self.context).data

class UpdateProviderProfileSerializer(serializers.ModelSerializer):
    """PATCH — mutable provider profile fields."""
    phone_number = serializers.CharField(source="user.phone_number", required=False)
    profile_picture = serializers.URLField(source="user.profile_picture")


    class Meta:
        model = ProviderProfile
        fields = [
            "full_name",
            "bio",
            "profile_picture",
            "hourly_rate",
            "experience_years",
            "service_radius_km",
            "location_lat",
            "location_lng",
            "location_address",
            "phone_number",
        ]

    def validate_phone_number(self, value):
        if value and not re.match(r"^\+\d{7,15}$", value):
            raise serializers.ValidationError("Phone must be E.164 format.")
        user = self.instance.user
        if User.objects.filter(phone_number=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Phone number already in use.")
        return value

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        user = instance.user
        if "phone_number" in user_data:
            instance.user.phone_number = user_data["phone_number"]
            instance.user.save(update_fields=["phone_number"])
        if "profile_picture" in user_data:
            instance.user.profile_picture = user_data["profile_picture"]
        if user_data:
            user.save()
        return super().update(instance, validated_data)



class ProviderListQuerySerializer(serializers.Serializer):
   
    category_slug = serializers.SlugField(required=False)
    lat = serializers.FloatField(required=False, min_value=-90, max_value=90)
    lng = serializers.FloatField(required=False, min_value=-180, max_value=180)
    radius_km = serializers.FloatField(
        required=False, min_value=0.1, max_value=500, default=50
    )
    min_rating = serializers.FloatField(
        required=False, min_value=0, max_value=5, default=0
    )
    min_jobs = serializers.IntegerField(required=False, min_value=0, default=0)

    def validate(self, attrs):
        has_lat = "lat" in attrs
        has_lng = "lng" in attrs
        if has_lat != has_lng:
            raise serializers.ValidationError(
                "lat and lng must both be provided together."
            )
        return attrs
    
    