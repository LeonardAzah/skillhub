from rest_framework import serializers

from ..models import (
    User,
    SeekerProfile,
    ProviderProfile,
)



#  Onboarding

class OnboardingSerializer(serializers.Serializer):
    """
    Post-email-verification step where user selects
    Service Seeker or Service Provider role.
    """
    account_type = serializers.ChoiceField(choices=User.AccountType.choices)

    def save(self):
        user: User = self.context["request"].user
        account_type = self.validated_data["account_type"]
        user.account_type = account_type
        user.role = account_type  # role mirrors account_type for seekers/providers
        user.save(update_fields=["account_type", "role"])

        # Create the role-specific profile stub
        if account_type == User.AccountType.SEEKER:
            SeekerProfile.objects.get_or_create(user=user)
        elif account_type == User.AccountType.PROVIDER:
            ProviderProfile.objects.get_or_create(user=user)

        return user