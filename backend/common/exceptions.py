"""Standardized `{"error": {...}}` envelope for all DRF API error responses."""

import logging

from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("supportpilot")

# Stable, client-facing error codes for common DRF exception families that
# otherwise all collapse into the generic "validation_error" fallback below.
# Order matters: the first matching class (via isinstance) wins, so more
# specific exceptions must precede their base classes.
_STABLE_CODE_BY_EXCEPTION = (
    (Throttled, "rate_limited"),
    (NotAuthenticated, "authentication_failed"),
    (AuthenticationFailed, "authentication_failed"),
    (PermissionDenied, "permission_denied"),
    (NotFound, "not_found"),
)


def _stable_code_for(exc) -> str | None:
    for exc_class, code in _STABLE_CODE_BY_EXCEPTION:
        if isinstance(exc, exc_class):
            return code
    return None


class ConflictError(APIException):
    """A request conflicts with current server-side state (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state of the resource."
    default_code = "conflict"


class SafeAPIError(APIException):
    """Handled application error with a stable public code and safe message."""

    # Annotated ``int`` (not left to Literal[400] inference) so a subclass
    # may safely override it with a different status code, matching
    # ``ConflictError`` above and any per-error-family subclasses elsewhere.
    status_code: int = status.HTTP_400_BAD_REQUEST
    api_error_code = "invalid_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.api_error_code = code or self.api_error_code
        super().__init__(message)


def custom_exception_handler(exc, context):
    """Normalize every handled DRF exception into a stable error envelope.

    Unhandled exceptions (response is None) become a generic 500 so raw
    vendor/traceback text never reaches the client.
    """
    response = exception_handler(exc, context)

    if response is None:
        # DRF could not map this to a known API exception. Log the full
        # traceback server-side for diagnosis — the client only ever sees
        # the generic envelope below, never vendor/traceback text.
        logger.exception("unhandled_exception", exc_info=exc)
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

    if isinstance(exc, SafeAPIError):
        response.data = {
            "error": {
                "code": exc.api_error_code,
                "message": str(exc.detail),
            }
        }
        return response

    if isinstance(data, dict) and "error" in data:
        # Already enveloped upstream; leave untouched (idempotent).
        return response

    if isinstance(data, dict) and "detail" in data:
        code = _stable_code_for(exc) or "validation_error"
        error = {
            "code": code,
            "message": str(data.get("detail", "Invalid request.")),
        }
        if isinstance(exc, Throttled) and exc.wait is not None:
            # Bounded, non-sensitive retry hint (Section 23) — never expose
            # the underlying Redis/cache implementation.
            error["details"] = {"retry_after": int(exc.wait)}
        response.data = {"error": error}
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
