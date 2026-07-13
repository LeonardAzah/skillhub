"""
Custom DRF exception handler.

Returns consistent error envelope:
{
    "success": false,
    "message": "Human-readable summary",
    "errors": { ... }   # field-level detail when available
}
"""

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler



def custom_exception_handler(exc, context):
    # Let DRF convert Django core exceptions first
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=exc.messages)
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception – 500
        return Response(
            {
                "success": False,
                "message": "An unexpected error occurred. Our team has been notified.",
                "errors": {},
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Normalise the response body
    errors = response.data
    if isinstance(errors, list):
        message = errors[0] if errors else "An error occurred."
        errors = {"non_field_errors": errors}
    elif isinstance(errors, dict):
        # Extract a human-readable top-level message
        if "detail" in errors:
            message = str(errors.pop("detail"))
        else:
            first_key = next(iter(errors), None)
            first_val = errors.get(first_key, "")
            if isinstance(first_val, list):
                message = str(first_val[0])
            else:
                message = str(first_val)
    else:
        message = str(errors)

    response.data = {
        "success": False,
        "message": message,
        "errors": errors,
    }
    return response


def error_response(message, status_code, data=None):
    """Shared shape for error responses: {success, message, data}."""
    return Response(
        {
            "success": False,
            "message": message,
            "data": data,
        },
        status=status_code,
    )