"""
Custom DRF permission classes implementing RBAC.
IsSeeker, IsProvider, IsAdmin, IsVerified
"""
from rest_framework.permissions import BasePermission


class IsSeeker(BasePermission):
    """
    Allows access only to users with role = 'seeker'.
    """
    message = "Only service seekers can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "seeker"
        )


class IsProvider(BasePermission):
    """
    Allows access only to users with role = 'provider'.
    """
    message = "Only service providers can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "provider"
        )


class IsAdmin(BasePermission):
    """
    Allows access only to admin users.
    """
    message = "Admin access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.role == "admin" or request.user.is_staff)
        )


class IsVerified(BasePermission):
    """
    Requires KYC verification to be completed.
    Users blocked from booking without completed KYC.
    """
    message = "KYC verification is required to perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_verified
        )


class IsEmailVerified(BasePermission):
    """Requires email to be verified."""
    message = "Please verify your email address before proceeding."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_email_verified
        )


class IsSeekerOrAdmin(BasePermission):
    """Seeker or Admin access."""
    message = "Seeker or admin access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ("seeker", "admin", None)
            or (request.user and request.user.is_staff)
        )


class IsProviderOrAdmin(BasePermission):
    """Provider or Admin access."""
    message = "Provider or admin access required."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.role in ("provider", "admin")
                or request.user.is_staff
            )
        )


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level permission: only the owner or an admin can access.
    Assumes the model has a `user` FK.
    """
    message = "You do not have permission to access this resource."

    def has_object_permission(self, request, view, obj):
        if request.user and (request.user.is_staff or request.user.role == "admin"):
            return True
        user_field = getattr(obj, "user", None)
        return user_field == request.user
