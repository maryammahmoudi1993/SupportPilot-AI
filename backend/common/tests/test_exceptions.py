"""Tests for the standardized `{"error": {...}}` API error envelope."""

from django.http import Http404
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.views import APIView

from common.exceptions import ConflictError, custom_exception_handler


def _context():
    return {"view": APIView(), "request": None, "args": [], "kwargs": {}}


class TestCustomExceptionHandler:
    def test_wraps_bare_validation_errors_in_the_error_envelope(self):
        response = custom_exception_handler(ValidationError("bad input"), _context())

        assert response is not None
        assert response.data["error"]["code"] == "validation_error"
        assert "bad input" in str(response.data["error"]["details"])

    def test_wraps_field_validation_errors_with_detail_dict(self):
        response = custom_exception_handler(
            ValidationError({"amount": "must be positive"}), _context()
        )

        assert response.data["error"]["code"] == "validation_error"
        assert str(response.data["error"]["details"]["amount"]) == "must be positive"

    def test_wraps_drf_not_found_in_the_error_envelope(self):
        response = custom_exception_handler(NotFound(), _context())

        assert response is not None
        assert response.status_code == 404
        assert "error" in response.data
        assert response.data["error"]["code"] == "not_found"

    def test_not_authenticated_maps_to_stable_authentication_failed_code(self):
        response = custom_exception_handler(NotAuthenticated(), _context())

        assert response.status_code == 401
        assert response.data["error"]["code"] == "authentication_failed"

    def test_authentication_failed_maps_to_stable_authentication_failed_code(self):
        response = custom_exception_handler(AuthenticationFailed(), _context())

        assert response.status_code == 401
        assert response.data["error"]["code"] == "authentication_failed"

    def test_django_http404_maps_to_stable_not_found_code(self):
        # P20-404-01 regression: `django.http.Http404` — the codebase's normal
        # not-found idiom in selectors (`workspaces/selectors.py`,
        # `agents/selectors.py`, `approvals/selectors.py`, etc.) — must
        # produce the same stable envelope as DRF's own `NotFound`, not fall
        # through to the generic "validation_error" fallback. DRF's own
        # `exception_handler()` converts `Http404` to `NotFound` only inside
        # its own local scope while building the Response body/status; this
        # asserts the *code* survives that same round trip through the real
        # `custom_exception_handler` entry point, not `_stable_code_for` in
        # isolation.
        response = custom_exception_handler(Http404("Approval request not found."), _context())

        assert response is not None
        assert response.status_code == 404
        assert response.data["error"]["code"] == "not_found"
        # The raw Http404 message becomes the safe "detail" text DRF itself
        # produces — never leaked verbatim beyond what NotFound already sends.
        assert "error" in response.data and "code" in response.data["error"]

    def test_django_http404_with_no_message_still_maps_to_not_found(self):
        # A bare `raise Http404()` (no message) is also common — must not
        # crash or regress to the generic fallback.
        response = custom_exception_handler(Http404(), _context())

        assert response.status_code == 404
        assert response.data["error"]["code"] == "not_found"

    def test_permission_denied_maps_to_stable_permission_denied_code(self):
        response = custom_exception_handler(PermissionDenied(), _context())

        assert response.status_code == 403
        assert response.data["error"]["code"] == "permission_denied"

    def test_throttled_maps_to_stable_rate_limited_code_with_retry_after(self):
        response = custom_exception_handler(Throttled(wait=12), _context())

        assert response.status_code == 429
        assert response.data["error"]["code"] == "rate_limited"
        assert response.data["error"]["details"]["retry_after"] == 12

    def test_throttled_without_wait_omits_retry_after_details(self):
        response = custom_exception_handler(Throttled(), _context())

        assert response.status_code == 429
        assert response.data["error"]["code"] == "rate_limited"
        assert "details" not in response.data["error"]

    def test_leaves_an_already_enveloped_response_untouched(self):
        exc = APIException()
        exc.detail = {"error": {"code": "custom_error", "message": "already wrapped"}}

        response = custom_exception_handler(exc, _context())

        assert response.data == {"error": {"code": "custom_error", "message": "already wrapped"}}

    def test_unhandled_exception_returns_generic_500_envelope(self):
        response = custom_exception_handler(RuntimeError("boom"), _context())

        assert response is not None
        assert response.status_code == 500
        assert response.data["error"]["code"] == "internal_server_error"
        # The raw exception message must never leak to the client.
        assert "boom" not in str(response.data)

    def test_conflict_error_maps_to_409(self):
        response = custom_exception_handler(ConflictError("already exists"), _context())

        assert response is not None
        assert response.status_code == 409
        assert "error" in response.data

    def test_unhandled_exception_marker_in_message_never_reaches_the_client(self):
        # Phase 15 Security Checkpoint 5 (Part D.2): a synthetic marker
        # standing in for a secret-shaped value that ends up in a raw,
        # unmapped exception's message must never appear in the JSON body
        # returned to the client — only the fixed generic envelope may.
        marker = "PHASE15_PASSWORD_MARKER_do-not-leak"
        response = custom_exception_handler(
            RuntimeError(f"provider call failed: password={marker}"), _context()
        )

        assert response is not None
        assert response.status_code == 500
        assert marker not in str(response.data)
        assert response.data == {
            "error": {
                "code": "internal_server_error",
                "message": "An internal server error occurred.",
            }
        }
