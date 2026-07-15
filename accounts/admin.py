from django.contrib import admin
from .models import User, ProviderProfile, SeekerProfile
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

# Register your models here.
# admin.site.register(User)
admin.site.register(ProviderProfile)
admin.site.register(SeekerProfile)

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]

    list_display = (
        "email",
        "username",
        "role",
        "is_staff",
        "is_active",
    )

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {
            "fields": (
                "username",
                "phone_number",
                "profile_picture",
            )
        }),
        ("Permissions", {
            "fields": (
                "role",
                "account_type",
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            )
        }),
        ("Important dates", {"fields": ("last_login",)}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "username",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

    search_fields = ("email", "username")