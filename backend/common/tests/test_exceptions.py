"""Tests for the standardized `{"error": {...}}` API error envelope."""

from rest_framework.exceptions import APIException, NotFound, ValidationError
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
        assert response.data["error"]["code"] == "validation_error"

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
