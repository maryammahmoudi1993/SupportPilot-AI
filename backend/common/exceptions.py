"""Standardized `{"error": {...}}` envelope for all DRF API error responses."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    """Normalize every handled DRF exception into a stable error envelope.

    Unhandled exceptions (response is None) become a generic 500 so raw
    vendor/traceback text never reaches the client.
    """
    response = exception_handler(exc, context)

    if response is None:
        return Response(
            {
                "error": {
                    "code": "internal_server_error",
                    "message": "An internal server error occurred.",
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data

    if isinstance(data, dict) and "error" in data:
        # Already enveloped upstream; leave untouched (idempotent).
        return response

    if isinstance(data, dict) and "detail" in data:
        response.data = {
            "error": {
                "code": "validation_error",
                "message": str(data.get("detail", "Invalid request.")),
            }
        }
        return response

    # Anything else DRF can produce for a handled exception — a dict of
    # field errors, or a bare list (e.g. `raise ValidationError("...")`).
    response.data = {
        "error": {
            "code": "validation_error",
            "message": "Invalid request.",
            "details": data,
        }
    }
    return response
