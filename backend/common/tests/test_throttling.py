"""Phase 14 (Section 22): the rate-limit test matrix across categories not
already covered by their owning app's own tests.

AUTH (login/refresh) and AGENT_EXECUTION/EVALUATION_EXECUTION are already
covered by accounts/tests/test_auth_views.py and Milestone 1's
agents/evaluations tests respectively — not duplicated here. This file
covers PUBLIC_CHAT, PUBLIC_SIGNED_INGRESS, SENSITIVE_MUTATION, and the
shared cache-outage fail-closed behavior (Section 19) that applies to
every scope uniformly via ``common.throttling.SafeScopedRateThrottle``.
"""

from __future__ import annotations

import json
import time
from unittest import mock

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from channel_ingress.security import compute_signature
from channel_ingress.tests.factories import (
    TEST_SIGNING_SECRET,
    ChannelEndpointFactory,
    WebChatEndpointFactory,
)
from common.throttling import SafeScopedRateThrottle
from webhooks.tests.factories import WebhookEndpointFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory


def _client() -> APIClient:
    return APIClient()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestPublicChatRateLimit:
    def _submit(self, client, token, remote_addr="10.0.0.1"):
        return client.post(
            f"/api/v1/channels/public/webchat/session/{token}/messages/",
            {"client_message_id": f"msg-{time.time_ns()}", "body": "hi"},
            format="json",
            REMOTE_ADDR=remote_addr,
        )

    def test_below_at_and_above_threshold(self):
        endpoint = WebChatEndpointFactory()
        client = _client()
        token = client.post(
            f"/api/v1/channels/public/webchat/{endpoint.id}/session/", REMOTE_ADDR="10.0.0.1"
        ).data["session_token"]

        with mock.patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"channel_webchat_message": "2/min"}
        ):
            first = self._submit(client, token)
            second = self._submit(client, token)
            assert first.status_code == 202
            assert second.status_code == 202  # at threshold — still allowed

            third = self._submit(client, token)
            assert third.status_code == 429
            assert third.data["error"]["code"] == "rate_limited"

    def test_isolation_by_network_identity(self):
        # PUBLIC_CHAT is unauthenticated by design (Section 45) — identity
        # is the caller's network address (server-derived, never a
        # caller-supplied session/workspace/customer id), so two distinct
        # source addresses get independent buckets even for the same scope.
        endpoint = WebChatEndpointFactory()
        client = _client()
        token = client.post(
            f"/api/v1/channels/public/webchat/{endpoint.id}/session/", REMOTE_ADDR="10.0.0.1"
        ).data["session_token"]

        with mock.patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"channel_webchat_message": "1/min"}
        ):
            first = self._submit(client, token, remote_addr="10.0.0.1")
            assert first.status_code == 202
            exhausted = self._submit(client, token, remote_addr="10.0.0.1")
            assert exhausted.status_code == 429

            from_other_address = self._submit(client, token, remote_addr="10.0.0.2")
            assert from_other_address.status_code == 202


@pytest.mark.django_db
class TestSignedIngressRateLimit:
    def _signed_post(self, endpoint, body: bytes, remote_addr="10.0.0.1"):
        ts = int(time.time())
        signature = compute_signature(secret=TEST_SIGNING_SECRET, timestamp=ts, raw_body=body)
        return _client().post(
            f"/api/v1/channels/public/inbound/{endpoint.id}/",
            data=body,
            content_type="application/json",
            HTTP_X_SUPPORTPILOT_TIMESTAMP=str(ts),
            HTTP_X_SUPPORTPILOT_SIGNATURE=signature,
            REMOTE_ADDR=remote_addr,
        )

    def test_below_at_and_above_threshold_for_valid_signed_requests(self):
        endpoint = ChannelEndpointFactory()
        with mock.patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"channel_inbound_webhook": "2/min"}
        ):
            for i in range(2):
                body = json.dumps(
                    {"event_id": f"evt-{i}", "external_id": "cust-1", "body": "hi"}
                ).encode()
                response = self._signed_post(endpoint, body)
                assert response.status_code == 202

            over_limit = self._signed_post(
                endpoint, json.dumps({"event_id": "evt-over", "external_id": "cust-1"}).encode()
            )
            assert over_limit.status_code == 429
            assert over_limit.data["error"]["code"] == "rate_limited"

    def test_invalid_signature_remains_fail_closed_under_throttling(self):
        # Rate limiting is defense-in-depth (Section 15) — it must never
        # weaken the primary signature-authentication boundary.
        endpoint = ChannelEndpointFactory()
        body = json.dumps({"event_id": "evt-1", "external_id": "cust-1"}).encode()
        ts = int(time.time())
        bad_signature = compute_signature(secret="wrong-secret", timestamp=ts, raw_body=body)
        response = _client().post(
            f"/api/v1/channels/public/inbound/{endpoint.id}/",
            data=body,
            content_type="application/json",
            HTTP_X_SUPPORTPILOT_TIMESTAMP=str(ts),
            HTTP_X_SUPPORTPILOT_SIGNATURE=bad_signature,
        )
        assert response.status_code == 400

    def test_isolation_by_network_identity(self):
        endpoint = ChannelEndpointFactory()
        with mock.patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"channel_inbound_webhook": "1/min"}
        ):
            body_a = json.dumps(
                {"event_id": "evt-a", "external_id": "cust-1", "body": "hi"}
            ).encode()
            first = self._signed_post(endpoint, body_a, remote_addr="10.0.0.1")
            assert first.status_code == 202
            exhausted = self._signed_post(
                endpoint,
                json.dumps({"event_id": "evt-a2", "external_id": "cust-1", "body": "hi"}).encode(),
                remote_addr="10.0.0.1",
            )
            assert exhausted.status_code == 429

            body_b = json.dumps(
                {"event_id": "evt-b", "external_id": "cust-1", "body": "hi"}
            ).encode()
            from_other_address = self._signed_post(endpoint, body_b, remote_addr="10.0.0.2")
            assert from_other_address.status_code == 202


@pytest.mark.django_db
class TestSensitiveMutationRateLimit:
    def test_secret_rotation_is_rate_limited(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        endpoint = WebhookEndpointFactory(workspace=membership.workspace)
        client = APIClient()
        client.force_authenticate(user=membership.user)
        url = (
            f"/api/v1/workspaces/{membership.workspace.id}/webhooks/endpoints/"
            f"{endpoint.id}/rotate-secret/"
        )

        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"sensitive_mutation": "1/min"}):
            first = client.post(url)
            assert first.status_code == 200

            second = client.post(url)
            assert second.status_code == 429
            assert second.data["error"]["code"] == "rate_limited"


@pytest.mark.django_db
class TestThrottleCacheOutage:
    """Section 19: a Redis/cache failure during throttle evaluation must
    fail closed with a bounded, stable 503 — never a raw 500 leaking cache
    internals, and never silently treated as 'allowed' (unlimited writes)
    or as an actual `rate_limited` rejection."""

    def test_cache_outage_returns_bounded_service_unavailable(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        endpoint = WebhookEndpointFactory(workspace=membership.workspace)
        client = APIClient()
        client.force_authenticate(user=membership.user)
        url = (
            f"/api/v1/workspaces/{membership.workspace.id}/webhooks/endpoints/"
            f"{endpoint.id}/rotate-secret/"
        )

        secret_dsn = "redis://:supersecretpassword@redis-host:6379/0"
        with mock.patch("rest_framework.throttling.SimpleRateThrottle.cache") as mock_cache:
            mock_cache.get.side_effect = Exception(secret_dsn)
            response = client.post(url)

        assert response.status_code == 503
        assert response.data["error"]["code"] == "service_unavailable"
        assert secret_dsn not in str(response.data)

    def test_cache_outage_never_reports_rate_limited(self):
        # A cache exception must be distinguishable from an actual
        # throttle rejection — a client must never be told it exceeded a
        # quota when the real problem is infrastructure.
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        endpoint = WebhookEndpointFactory(workspace=membership.workspace)
        client = APIClient()
        client.force_authenticate(user=membership.user)
        url = (
            f"/api/v1/workspaces/{membership.workspace.id}/webhooks/endpoints/"
            f"{endpoint.id}/rotate-secret/"
        )

        with mock.patch("rest_framework.throttling.SimpleRateThrottle.cache") as mock_cache:
            mock_cache.get.side_effect = Exception("connection refused")
            response = client.post(url)

        assert response.data["error"]["code"] != "rate_limited"

    def test_healthy_cache_path_is_unaffected(self):
        # Sanity check: SafeScopedRateThrottle behaves exactly like the
        # underlying ScopedRateThrottle when the cache is healthy.
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        endpoint = WebhookEndpointFactory(workspace=membership.workspace)
        client = APIClient()
        client.force_authenticate(user=membership.user)
        url = (
            f"/api/v1/workspaces/{membership.workspace.id}/webhooks/endpoints/"
            f"{endpoint.id}/rotate-secret/"
        )
        response = client.post(url)
        assert response.status_code == 200

    def test_safe_scoped_rate_throttle_wraps_cache_exception_directly(self):
        # Unit-level proof independent of any specific view/scope.
        from common.throttling import ThrottleCacheUnavailable

        throttle = SafeScopedRateThrottle()
        with mock.patch(
            "rest_framework.throttling.ScopedRateThrottle.allow_request",
            side_effect=Exception("boom"),
        ):
            with pytest.raises(ThrottleCacheUnavailable):
                throttle.allow_request(request=None, view=None)
