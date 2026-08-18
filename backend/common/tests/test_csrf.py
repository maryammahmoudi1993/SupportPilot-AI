"""Unit tests for the manual CSRF-enforcement helper used by cookie-
authenticated auth endpoints."""

import pytest
from django.conf import settings
from django.middleware.csrf import get_token
from django.test import RequestFactory
from rest_framework.exceptions import PermissionDenied

from common.csrf import enforce_csrf


class TestEnforceCsrf:
    def test_raises_when_no_csrf_cookie_present(self):
        request = RequestFactory().post("/")
        with pytest.raises(PermissionDenied):
            enforce_csrf(request)

    def test_passes_with_a_matching_cookie_and_header(self):
        priming_request = RequestFactory().get("/")
        token = get_token(priming_request)

        request = RequestFactory().post("/", HTTP_X_CSRFTOKEN=token)
        request.COOKIES[settings.CSRF_COOKIE_NAME] = token

        # Should not raise.
        enforce_csrf(request)

    def test_raises_when_header_does_not_match_cookie(self):
        priming_request = RequestFactory().get("/")
        token = get_token(priming_request)

        request = RequestFactory().post("/", HTTP_X_CSRFTOKEN="mismatched-token")
        request.COOKIES[settings.CSRF_COOKIE_NAME] = token

        with pytest.raises(PermissionDenied):
            enforce_csrf(request)
