"""Tests for accounts.services: credential verification and token issuance."""

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from rest_framework.exceptions import AuthenticationFailed

from accounts.services import (
    authenticate_by_email,
    clear_refresh_cookie,
    issue_tokens_for_user,
    set_refresh_cookie,
)
from accounts.tests.factories import DEFAULT_PASSWORD, UserFactory


@pytest.mark.django_db
class TestAuthenticateByEmail:
    def test_returns_the_user_for_correct_credentials(self):
        user = UserFactory(email="jane@example.com")
        request = RequestFactory().post("/")

        result = authenticate_by_email(
            request=request, email="jane@example.com", password=DEFAULT_PASSWORD
        )

        assert result == user

    def test_email_lookup_is_case_insensitive(self):
        user = UserFactory(email="jane@example.com")
        request = RequestFactory().post("/")

        result = authenticate_by_email(
            request=request, email="JANE@EXAMPLE.COM", password=DEFAULT_PASSWORD
        )
        assert result == user

    def test_raises_generic_error_for_wrong_password(self):
        UserFactory(email="jane@example.com")
        request = RequestFactory().post("/")

        with pytest.raises(AuthenticationFailed):
            authenticate_by_email(request=request, email="jane@example.com", password="wrong")

    def test_raises_generic_error_for_unknown_email(self):
        request = RequestFactory().post("/")
        with pytest.raises(AuthenticationFailed):
            authenticate_by_email(request=request, email="nobody@example.com", password="x")

    def test_raises_generic_error_for_inactive_user(self):
        UserFactory(email="jane@example.com", is_active=False)
        request = RequestFactory().post("/")

        with pytest.raises(AuthenticationFailed):
            authenticate_by_email(
                request=request, email="jane@example.com", password=DEFAULT_PASSWORD
            )


@pytest.mark.django_db
class TestTokenIssuance:
    def test_issues_a_distinct_access_and_refresh_token(self):
        user = UserFactory()
        access, refresh = issue_tokens_for_user(user)
        assert access != refresh
        assert isinstance(access, str)
        assert isinstance(refresh, str)


class TestRefreshCookieHelpers:
    def test_set_refresh_cookie_sets_expected_attributes(self, settings):
        response = HttpResponse()
        set_refresh_cookie(response, "raw-token-value")

        cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
        assert cookie.value == "raw-token-value"
        assert cookie["httponly"]
        assert cookie["path"] == settings.AUTH_REFRESH_COOKIE_PATH
        assert cookie["samesite"] == settings.AUTH_REFRESH_COOKIE_SAMESITE

    def test_clear_refresh_cookie_expires_it(self, settings):
        response = HttpResponse()
        clear_refresh_cookie(response)

        cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
        assert cookie["max-age"] == 0
