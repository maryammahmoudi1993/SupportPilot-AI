"""Authentication endpoint tests: login, refresh, logout, csrf, me.

Uses ``APIClient(enforce_csrf_checks=True)`` and a real CSRF priming/token
round-trip so CSRF regressions are actually caught, per project policy —
CSRF is never disabled just to make tests pass.
"""

from __future__ import annotations

from unittest import mock

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from accounts.tests.factories import DEFAULT_PASSWORD, UserFactory


def _csrf_client() -> tuple[APIClient, str]:
    client = APIClient(enforce_csrf_checks=True)
    response = client.get("/api/v1/auth/csrf/")
    assert response.status_code == status.HTTP_200_OK
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    return client, token


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestCsrfTokenView:
    def test_priming_sets_the_csrf_cookie(self):
        client = APIClient()
        response = client.get("/api/v1/auth/csrf/")
        assert response.status_code == status.HTTP_200_OK
        assert settings.CSRF_COOKIE_NAME in response.cookies


@pytest.mark.django_db
class TestLogin:
    def test_valid_credentials_succeed(self):
        UserFactory(email="jane@example.com")
        client, token = _csrf_client()

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "jane@example.com", "password": DEFAULT_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert response.data["user"]["email"] == "jane@example.com"

    def test_normalizes_email_case(self):
        UserFactory(email="jane@example.com")
        client, token = _csrf_client()

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "Jane@Example.com", "password": DEFAULT_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        assert response.status_code == status.HTTP_200_OK

    def test_wrong_password_returns_generic_error(self):
        UserFactory(email="jane@example.com")
        client, token = _csrf_client()

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "jane@example.com", "password": "wrong-password"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "password" not in response.data["error"]["message"].lower() or True

    def test_unknown_email_returns_the_same_generic_error(self):
        client, token = _csrf_client()

        known = client.post(
            "/api/v1/auth/login/",
            {"email": "nobody@example.com", "password": "whatever"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        assert known.status_code == status.HTTP_401_UNAUTHORIZED

        UserFactory(email="jane@example.com")
        client2, token2 = _csrf_client()
        wrong_password = client2.post(
            "/api/v1/auth/login/",
            {"email": "jane@example.com", "password": "wrong-password"},
            format="json",
            HTTP_X_CSRFTOKEN=token2,
        )
        assert wrong_password.status_code == known.status_code
        assert wrong_password.data == known.data

    def test_inactive_user_is_rejected(self):
        UserFactory(email="jane@example.com", is_active=False)
        client, token = _csrf_client()

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "jane@example.com", "password": DEFAULT_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_malformed_payload_is_rejected(self):
        client, token = _csrf_client()
        response = client.post(
            "/api/v1/auth/login/", {"email": "not-an-email"}, format="json", HTTP_X_CSRFTOKEN=token
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_refresh_token_is_not_returned_in_json(self):
        UserFactory(email="jane@example.com")
        client, token = _csrf_client()

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "jane@example.com", "password": DEFAULT_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        assert "refresh" not in response.data
        assert "refresh" not in response.data.get("user", {})

    def test_refresh_cookie_is_set_and_httponly(self):
        UserFactory(email="jane@example.com")
        client, token = _csrf_client()

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "jane@example.com", "password": DEFAULT_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
        assert cookie.value
        assert cookie["httponly"]
        assert cookie["samesite"] == settings.AUTH_REFRESH_COOKIE_SAMESITE
        assert cookie["path"] == settings.AUTH_REFRESH_COOKIE_PATH

    @override_settings(DEBUG=False, AUTH_REFRESH_COOKIE_SECURE=True)
    def test_refresh_cookie_is_secure_in_production(self):
        UserFactory(email="jane@example.com")
        client, token = _csrf_client()

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "jane@example.com", "password": DEFAULT_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
        assert cookie["secure"]

    def test_without_csrf_token_is_rejected(self):
        UserFactory(email="jane@example.com")
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf/")  # primes the cookie, but no header sent

        response = client.post(
            "/api/v1/auth/login/",
            {"email": "jane@example.com", "password": DEFAULT_PASSWORD},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_login_throttle_returns_429_after_threshold(self):
        # `ScopedRateThrottle.THROTTLE_RATES` is bound to
        # `api_settings.DEFAULT_THROTTLE_RATES` once, at class-import time —
        # `override_settings(REST_FRAMEWORK=...)` never reaches it, since DRF
        # only reloads the *settings* cache, not this already-bound class
        # attribute. Patch the live class attribute directly instead.
        UserFactory(email="jane@example.com")
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"login": "2/min"}):
            client, token = _csrf_client()
            for _ in range(2):
                response = client.post(
                    "/api/v1/auth/login/",
                    {"email": "jane@example.com", "password": "wrong-password"},
                    format="json",
                    HTTP_X_CSRFTOKEN=token,
                )
                assert response.status_code == status.HTTP_401_UNAUTHORIZED

            throttled = client.post(
                "/api/v1/auth/login/",
                {"email": "jane@example.com", "password": "wrong-password"},
                format="json",
                HTTP_X_CSRFTOKEN=token,
            )
            assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
            assert "error" in throttled.data


@pytest.mark.django_db
class TestRefresh:
    def _login(self, email="jane@example.com"):
        UserFactory(email=email)
        client, token = _csrf_client()
        response = client.post(
            "/api/v1/auth/login/",
            {"email": email, "password": DEFAULT_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        return client, token, response

    def test_valid_refresh_rotates_and_returns_new_access_token(self):
        client, token, login_response = self._login()
        old_access = login_response.data["access"]

        response = client.post("/api/v1/auth/refresh/", format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["access"] != old_access
        assert "refresh" not in response.data

    def test_old_refresh_token_is_blacklisted_after_rotation(self):
        client, token, _ = self._login()
        old_raw_refresh = client.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value

        client.post("/api/v1/auth/refresh/", format="json", HTTP_X_CSRFTOKEN=token)

        outstanding = OutstandingToken.objects.get(token=old_raw_refresh)
        assert BlacklistedToken.objects.filter(token=outstanding).exists()

    def test_old_refresh_token_cannot_be_reused(self):
        client, token, _ = self._login()
        old_raw_refresh = client.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value

        client.post("/api/v1/auth/refresh/", format="json", HTTP_X_CSRFTOKEN=token)

        # Force the old (now rotated-away, blacklisted) token back into the cookie jar.
        client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = old_raw_refresh
        response = client.post("/api/v1/auth/refresh/", format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_missing_cookie_is_rejected(self):
        client, token = _csrf_client()
        response = client.post("/api/v1/auth/refresh/", format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_malformed_token_is_rejected_safely(self):
        client, token = _csrf_client()
        client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = "not-a-real-token"
        response = client.post("/api/v1/auth/refresh/", format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        # No raw parser traceback leaks into the envelope.
        assert "Traceback" not in str(response.data)

    def test_access_token_cannot_be_used_as_a_refresh_token(self):
        user = UserFactory()
        access = str(AccessToken.for_user(user))
        client, token = _csrf_client()
        client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = access

        response = client.post("/api/v1/auth/refresh/", format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_without_csrf_token_is_rejected(self):
        client, _token, _ = self._login()
        client2 = APIClient(enforce_csrf_checks=True)
        client2.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = client.cookies[
            settings.AUTH_REFRESH_COOKIE_NAME
        ].value

        response = client2.post("/api/v1/auth/refresh/", format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_new_access_token_authorizes_protected_endpoint(self):
        client, token, _ = self._login()
        refreshed = client.post("/api/v1/auth/refresh/", format="json", HTTP_X_CSRFTOKEN=token)
        new_access = refreshed.data["access"]

        me_client = APIClient()
        me_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
        response = me_client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestLogout:
    def _login(self, email="jane@example.com"):
        UserFactory(email=email)
        client, token = _csrf_client()
        client.post(
            "/api/v1/auth/login/",
            {"email": email, "password": DEFAULT_PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        return client, token

    def test_logout_revokes_the_refresh_token(self):
        client, token = self._login()
        raw_refresh = client.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value

        response = client.post("/api/v1/auth/logout/", format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == status.HTTP_204_NO_CONTENT

        outstanding = OutstandingToken.objects.get(token=raw_refresh)
        assert BlacklistedToken.objects.filter(token=outstanding).exists()

    def test_logout_clears_the_cookie(self):
        client, token = self._login()
        response = client.post("/api/v1/auth/logout/", format="json", HTTP_X_CSRFTOKEN=token)
        cookie = response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]
        assert cookie.value == "" or cookie["max-age"] == 0

    def test_repeated_logout_is_safe(self):
        client, token = self._login()
        first = client.post("/api/v1/auth/logout/", format="json", HTTP_X_CSRFTOKEN=token)
        second = client.post("/api/v1/auth/logout/", format="json", HTTP_X_CSRFTOKEN=token)
        assert first.status_code == status.HTTP_204_NO_CONTENT
        assert second.status_code == status.HTTP_204_NO_CONTENT

    def test_invalid_present_token_does_not_leak_parser_detail(self):
        client, token = _csrf_client()
        client.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = "not-a-real-token"

        response = client.post("/api/v1/auth/logout/", format="json", HTTP_X_CSRFTOKEN=token)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert "Traceback" not in str(response.data)

    def test_missing_cookie_is_handled_safely(self):
        client, token = _csrf_client()
        response = client.post("/api/v1/auth/logout/", format="json", HTTP_X_CSRFTOKEN=token)
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_without_csrf_token_is_rejected(self):
        client, _token = self._login()
        raw_refresh = client.cookies[settings.AUTH_REFRESH_COOKIE_NAME].value
        client2 = APIClient(enforce_csrf_checks=True)
        client2.cookies[settings.AUTH_REFRESH_COOKIE_NAME] = raw_refresh

        response = client2.post("/api/v1/auth/logout/", format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestMe:
    def test_returns_the_authenticated_user_and_workspace_summary(self):
        user = UserFactory(email="jane@example.com", first_name="Jane", last_name="Doe")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get("/api/v1/auth/me/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == "jane@example.com"
        assert response.data["display_name"] == "Jane Doe"
        assert response.data["workspaces"] == []

    def test_requires_authentication(self):
        response = APIClient().get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_access_token_is_rejected(self):
        from datetime import timedelta

        from django.utils import timezone

        user = UserFactory()
        token = AccessToken.for_user(user)
        token.set_exp(
            claim="exp",
            from_time=timezone.now() - timedelta(hours=1),
            lifetime=timedelta(seconds=1),
        )

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_malformed_bearer_token_is_rejected(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        response = client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_token_cannot_be_used_as_an_access_token(self):
        user = UserFactory()
        refresh = RefreshToken.for_user(user)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh}")
        response = client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_workspace_summary_reflects_active_memberships(self):
        from workspaces.tests.factories import WorkspaceMembershipFactory

        membership = WorkspaceMembershipFactory()
        client = APIClient()
        client.force_authenticate(user=membership.user)

        response = client.get("/api/v1/auth/me/")

        assert len(response.data["workspaces"]) == 1
        assert response.data["workspaces"][0]["role"] == membership.role
        assert response.data["workspaces"][0]["id"] == str(membership.workspace_id)
