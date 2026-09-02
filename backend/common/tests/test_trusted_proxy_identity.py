"""Phase 14 trusted-proxy remediation: DRF derives unauthenticated throttle
identity via ``SimpleRateThrottle.get_ident`` (``rest_framework.throttling``).
Reading the installed DRF 3.17.2 source directly:

    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    remote_addr = request.META.get('REMOTE_ADDR')
    num_proxies = api_settings.NUM_PROXIES
    if num_proxies is not None:
        if num_proxies == 0 or xff is None:
            return remote_addr
        addrs = xff.split(',')
        client_addr = addrs[-min(num_proxies, len(addrs))]
        return client_addr.strip()
    return ''.join(xff.split()) if xff else remote_addr

With DRF's own default (``NUM_PROXIES = None``, previously unset in this
repository's ``REST_FRAMEWORK`` dict), any caller-supplied
``X-Forwarded-For`` was trusted outright — a direct, unauthenticated client
could rotate it to obtain a fresh throttle bucket on every request. This
repository now sets ``NUM_PROXIES`` explicitly via the ``DRF_NUM_PROXIES``
environment variable (default ``0``: no trusted reverse proxy, forwarded
headers are never trusted, identity is always ``REMOTE_ADDR``).

These tests prove: (1) the default configuration is resistant to
``X-Forwarded-For`` rotation on real public/auth endpoints, (2) the
``NUM_PROXIES=N`` knob behaves exactly as DRF documents when a deployment
does have trusted proxies, and (3) ``DRF_NUM_PROXIES`` parsing rejects
malformed values rather than silently degrading trust.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework.throttling import BaseThrottle, ScopedRateThrottle

from accounts.tests.factories import UserFactory
from channel_ingress.tests.factories import WebChatEndpointFactory


def _request(remote_addr: str, forwarded_for: str | None):
    meta = {"REMOTE_ADDR": remote_addr}
    if forwarded_for is not None:
        meta["HTTP_X_FORWARDED_FOR"] = forwarded_for
    return SimpleNamespace(META=meta)


def _throttle_rate(scope: str, rate: str):
    return mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {scope: rate})


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


class TestDefaultConfigurationIgnoresForwardedFor:
    """Section 7/10: with the repository's actual default (NUM_PROXIES=0,
    via DRF_NUM_PROXIES), a caller-supplied X-Forwarded-For never changes
    the derived identity."""

    def test_get_ident_ignores_rotating_forwarded_for(self):
        throttle = BaseThrottle()
        first = throttle.get_ident(_request("203.0.113.9", "198.51.100.1"))
        second = throttle.get_ident(_request("203.0.113.9", "198.51.100.2"))
        third = throttle.get_ident(_request("203.0.113.9", None))
        assert first == second == third == "203.0.113.9"


@pytest.mark.django_db
class TestPublicChatResistsForwardedForRotation:
    """Section 7: a direct client rotating X-Forwarded-For against a real
    PUBLIC_CHAT endpoint must land in the same throttle bucket and must not
    be able to evade the limit."""

    def test_rotating_forwarded_for_maps_to_the_same_bucket_and_is_blocked(self):
        endpoint = WebChatEndpointFactory()
        client = APIClient()
        token = client.post(
            f"/api/v1/channels/public/webchat/{endpoint.id}/session/",
            REMOTE_ADDR="10.0.0.1",
        ).data["session_token"]

        forwarded_addrs = ["198.51.100.1", "198.51.100.2", "198.51.100.3"]
        with _throttle_rate("channel_webchat_message", "2/min"):
            responses = [
                client.post(
                    f"/api/v1/channels/public/webchat/session/{token}/messages/",
                    {"client_message_id": f"msg-{i}", "body": "hi"},
                    format="json",
                    REMOTE_ADDR="10.0.0.1",
                    HTTP_X_FORWARDED_FOR=xff,
                )
                for i, xff in enumerate(forwarded_addrs)
            ]

        # Same REMOTE_ADDR, three different X-Forwarded-For values: still
        # one bucket. First two allowed (limit is 2/min), the third —
        # despite a brand-new spoofed X-Forwarded-For — is rejected.
        assert [r.status_code for r in responses] == [202, 202, 429]
        assert responses[-1].data["error"]["code"] == "rate_limited"


@pytest.mark.django_db
class TestAuthResistsForwardedForRotation:
    """Section 8: unauthenticated login throttling uses the same DRF
    identity mechanism — rotating X-Forwarded-For must not reset it."""

    def test_rotating_forwarded_for_does_not_reset_login_throttle(self):
        UserFactory(email="jane@example.com")
        client = APIClient(enforce_csrf_checks=True)
        csrf_response = client.get("/api/v1/auth/csrf/")
        assert csrf_response.status_code == 200
        token = client.cookies[settings.CSRF_COOKIE_NAME].value

        forwarded_addrs = ["198.51.100.1", "198.51.100.2", "198.51.100.3"]
        with _throttle_rate("login", "2/min"):
            responses = [
                client.post(
                    "/api/v1/auth/login/",
                    {"email": "jane@example.com", "password": "wrong-password"},
                    format="json",
                    HTTP_X_CSRFTOKEN=token,
                    REMOTE_ADDR="10.0.0.1",
                    HTTP_X_FORWARDED_FOR=xff,
                )
                for xff in forwarded_addrs
            ]

        # Generic credential-failure behavior is preserved for the first
        # two attempts (still 401, not leaking throttle state), and the
        # third — despite rotating X-Forwarded-For — is rate-limited, not a
        # fresh 401.
        assert responses[0].status_code == 401
        assert responses[1].status_code == 401
        assert responses[2].status_code == 429
        assert responses[2].data["error"]["code"] == "rate_limited"


class TestTrustedProxyModeAppliesDrfsOwnAlgorithm:
    """Section 9: proves the NUM_PROXIES configuration knob itself works,
    per DRF's documented algorithm — not a claim that any specific
    deployment's proxy is trustworthy."""

    def test_num_proxies_one_takes_the_last_forwarded_address(self):
        # client -> one trusted proxy -> Django. The proxy appends the
        # client's real address to X-Forwarded-For; DRF's documented
        # algorithm (NUM_PROXIES=1) takes the right-most address.
        with override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}):
            throttle = BaseThrottle()
            request = _request("10.0.0.1", "203.0.113.55")
            assert throttle.get_ident(request) == "203.0.113.55"

    def test_num_proxies_one_ignores_client_supplied_extra_hops(self):
        # A malicious direct client (no real proxy) sending a multi-hop XFF
        # still only affects the identity DRF's own algorithm dictates for
        # NUM_PROXIES=1 — proving the knob's *mechanism*, independent of
        # whether the deployment actually has a proxy sanitizing this.
        with override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}):
            throttle = BaseThrottle()
            request = _request("10.0.0.1", "1.2.3.4, 203.0.113.55")
            assert throttle.get_ident(request) == "203.0.113.55"


class TestDrfNumProxiesEnvironmentParsing:
    """Section 10: malformed DRF_NUM_PROXIES must fail configuration
    validation clearly, never silently degrade into trusting forwarded
    headers (DRF's own None default)."""

    def _run(self, env_value: str | None) -> subprocess.CompletedProcess:
        backend_root = str(Path(__file__).resolve().parent.parent.parent)
        child_script = textwrap.dedent("""
            import django
            django.setup()
            from django.conf import settings
            print("NUM_PROXIES=" + repr(settings.REST_FRAMEWORK["NUM_PROXIES"]))
            """)
        env = os.environ.copy()
        env.pop("DRF_NUM_PROXIES", None)
        if env_value is not None:
            env["DRF_NUM_PROXIES"] = env_value
        env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        return subprocess.run(
            [sys.executable, "-c", child_script],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=backend_root,
            env=env,
        )

    def test_missing_uses_safe_default_zero(self):
        result = self._run(None)
        assert result.returncode == 0, result.stderr
        assert "NUM_PROXIES=0" in result.stdout

    def test_zero_is_accepted(self):
        result = self._run("0")
        assert result.returncode == 0, result.stderr
        assert "NUM_PROXIES=0" in result.stdout

    def test_positive_integer_is_accepted(self):
        result = self._run("2")
        assert result.returncode == 0, result.stderr
        assert "NUM_PROXIES=2" in result.stdout

    def test_negative_is_rejected(self):
        result = self._run("-1")
        assert result.returncode != 0
        assert "DRF_NUM_PROXIES must be >= 0" in result.stderr

    def test_non_integer_is_rejected(self):
        result = self._run("not-a-number")
        assert result.returncode != 0
        assert "invalid literal for int()" in result.stderr
