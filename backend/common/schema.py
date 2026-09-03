"""Shared OpenAPI documentation helpers for the stable `{"error": {...}}`
envelope (Section 12-15). A single source of truth so representative
endpoints document the same error shape instead of each view improvising
its own ad hoc description.

This intentionally does not attempt to enumerate every domain-specific
error code (there are many, and they are already covered by their own
regression tests next to the code that raises them) — only the small set
of codes that recur across most of the API, per `common.exceptions`.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, inline_serializer
from rest_framework import serializers

# The stable, cross-cutting codes produced by common.exceptions.custom_exception_handler.
# Domain-specific SafeAPIError codes (e.g. "agent_version_not_published",
# "webhook_destination_blocked") are additional and documented at their own
# endpoints, not repeated here.
STABLE_ERROR_CODES = (
    "validation_error",
    "authentication_failed",
    "permission_denied",
    "not_found",
    "conflict",
    "rate_limited",
    "internal_server_error",
)

ErrorEnvelopeSerializer = inline_serializer(
    name="ErrorEnvelope",
    fields={
        "error": inline_serializer(
            name="ErrorDetail",
            fields={
                "code": serializers.ChoiceField(choices=STABLE_ERROR_CODES),
                "message": serializers.CharField(),
                "details": serializers.JSONField(required=False),
            },
        )
    },
)


def error_response(description: str, *, examples: list[OpenApiExample] | None = None):
    """A documented, reusable error-envelope response for representative
    endpoints (Section 15)."""
    return OpenApiResponse(
        response=ErrorEnvelopeSerializer,
        description=description,
        examples=examples,
    )


RATE_LIMITED_EXAMPLE = OpenApiExample(
    "Rate limited",
    value={
        "error": {
            "code": "rate_limited",
            "message": "Request was throttled.",
            "details": {"retry_after": 30},
        }
    },
    response_only=True,
    status_codes=["429"],
)

AUTHENTICATION_FAILED_EXAMPLE = OpenApiExample(
    "Authentication failed",
    value={"error": {"code": "authentication_failed", "message": "Invalid credentials."}},
    response_only=True,
    status_codes=["401"],
)
