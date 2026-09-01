"""Channel endpoint management API: RBAC, tenant isolation, secret-free
responses (mirrors ``webhooks.tests.test_views``); plus the public
webchat/inbound-webhook HTTP surface (Phase 13 section 44-45, 51, 58-59)."""

from __future__ import annotations

import json
import time

import pytest
from rest_framework.test import APIClient

from agents.tests.factories import PublishedAgentVersionFactory
from channel_ingress.models import ChannelEndpoint, ChannelType
from channel_ingress.security import compute_signature
from channel_ingress.tests.factories import (
    TEST_SIGNING_SECRET,
    ChannelEndpointFactory,
    EmailEndpointFactory,
    WebChatEndpointFactory,
)
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace) -> str:
    return f"/api/v1/workspaces/{workspace.id}/channels"


@pytest.mark.django_db
class TestEndpointListCreate:
    def test_anonymous_is_401(self):
        membership = WorkspaceMembershipFactory()
        assert _client().get(f"{_base(membership.workspace)}/endpoints/").status_code == 401

    def test_any_member_can_list_but_response_excludes_secret(self):
        endpoint = EmailEndpointFactory()
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).get(f"{_base(membership.workspace)}/endpoints/")
        assert response.status_code == 200
        payload = response.data["results"][0]
        assert "encrypted_signing_secret" not in payload
        assert "signing_secret" not in payload
        assert TEST_SIGNING_SECRET not in str(response.data)
        assert payload["secret_configured"] is True

    @pytest.mark.parametrize(
        "role,allowed",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, True),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_create_requires_manage_role(self, role, allowed):
        membership = WorkspaceMembershipFactory(role=role)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/endpoints/",
            {
                "channel": ChannelType.EMAIL,
                "name": "Support inbox",
                "agent_version_id": str(version.id),
            },
            format="json",
        )
        if allowed:
            assert response.status_code == 201
            assert response.data["signing_secret"]
            assert ChannelEndpoint.objects.filter(workspace=membership.workspace).count() == 1
        else:
            assert response.status_code == 403

    def test_web_chat_create_returns_no_signing_secret(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/endpoints/",
            {
                "channel": ChannelType.WEB_CHAT,
                "name": "Website widget",
                "agent_version_id": str(version.id),
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["signing_secret"] is None

    def test_create_rejects_an_agent_version_from_another_workspace(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        foreign_version = PublishedAgentVersionFactory()
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/endpoints/",
            {
                "channel": ChannelType.EMAIL,
                "name": "Support inbox",
                "agent_version_id": str(foreign_version.id),
            },
            format="json",
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestEndpointTenantIsolation:
    def test_foreign_workspace_endpoint_id_404s(self):
        endpoint = EmailEndpointFactory()
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/endpoints/{endpoint.id}/"
        )
        assert response.status_code == 404

    def test_rotate_secret_requires_manage_role(self):
        endpoint = EmailEndpointFactory()
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        response = _client(membership.user).post(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/rotate-secret/"
        )
        assert response.status_code == 403

    def test_rotate_secret_returns_a_fresh_plaintext_secret_once(self):
        endpoint = EmailEndpointFactory()
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).post(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/rotate-secret/"
        )
        assert response.status_code == 200
        new_secret = response.data["signing_secret"]
        assert new_secret != TEST_SIGNING_SECRET

    def test_disable_endpoint(self):
        endpoint = EmailEndpointFactory()
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).patch(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/status/",
            {"status": "disabled"},
            format="json",
        )
        assert response.status_code == 200
        endpoint.refresh_from_db()
        assert endpoint.status == "disabled"


# ---------------------------------------------------------------------------
# Public ingress HTTP surface
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInboundWebhookView:
    def _signed_post(self, endpoint, body: bytes, secret: str = TEST_SIGNING_SECRET):
        ts = int(time.time())
        signature = compute_signature(secret=secret, timestamp=ts, raw_body=body)
        return _client().post(
            f"/api/v1/channels/public/inbound/{endpoint.id}/",
            data=body,
            content_type="application/json",
            HTTP_X_SUPPORTPILOT_TIMESTAMP=str(ts),
            HTTP_X_SUPPORTPILOT_SIGNATURE=signature,
        )

    def test_valid_signed_event_is_accepted(self):
        endpoint = ChannelEndpointFactory()
        body = json.dumps({"event_id": "evt-1", "external_id": "cust-1", "body": "hi"}).encode()
        response = self._signed_post(endpoint, body)
        assert response.status_code == 202
        assert response.data["accepted"] is True

    def test_duplicate_valid_event_is_idempotently_accepted(self):
        endpoint = ChannelEndpointFactory()
        body = json.dumps({"event_id": "evt-1", "external_id": "cust-1", "body": "hi"}).encode()
        first = self._signed_post(endpoint, body)
        second = self._signed_post(endpoint, body)
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.data["event_id"] == second.data["event_id"]

    def test_bad_signature_fails_closed_without_leaking_detail(self):
        endpoint = ChannelEndpointFactory()
        body = json.dumps({"event_id": "evt-1", "external_id": "cust-1", "body": "hi"}).encode()
        response = self._signed_post(endpoint, body, secret="wrong-secret")
        assert response.status_code == 400
        assert "traceback" not in str(response.data).lower()
        assert TEST_SIGNING_SECRET not in str(response.data)

    def test_unknown_endpoint_id_404s_indistinguishably_from_disabled(self):
        import uuid

        response = _client().post(
            f"/api/v1/channels/public/inbound/{uuid.uuid4()}/",
            data=b"{}",
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_disabled_endpoint_404s(self):
        endpoint = ChannelEndpointFactory(status="disabled")
        body = json.dumps({"event_id": "evt-1", "external_id": "cust-1", "body": "hi"}).encode()
        response = self._signed_post(endpoint, body)
        assert response.status_code == 404


@pytest.mark.django_db
class TestWebChatPublicViews:
    def test_bootstrap_submit_and_list_round_trip(self):
        endpoint = WebChatEndpointFactory()
        client = _client()

        bootstrap = client.post(f"/api/v1/channels/public/webchat/{endpoint.id}/session/")
        assert bootstrap.status_code == 201
        token = bootstrap.data["session_token"]

        submit = client.post(
            f"/api/v1/channels/public/webchat/session/{token}/messages/",
            {"client_message_id": "msg-1", "body": "Hello"},
            format="json",
        )
        assert submit.status_code == 202

        listing = client.get(f"/api/v1/channels/public/webchat/session/{token}/messages/")
        assert listing.status_code == 200

    def test_invalid_session_token_is_rejected(self):
        response = _client().post(
            "/api/v1/channels/public/webchat/session/not-a-real-token/messages/",
            {"client_message_id": "msg-1", "body": "hi"},
            format="json",
        )
        assert response.status_code == 400

    def test_one_session_cannot_read_another_sessions_messages(self):
        endpoint = WebChatEndpointFactory()
        client = _client()
        token_a = client.post(f"/api/v1/channels/public/webchat/{endpoint.id}/session/").data[
            "session_token"
        ]
        token_b = client.post(f"/api/v1/channels/public/webchat/{endpoint.id}/session/").data[
            "session_token"
        ]
        assert token_a != token_b
        response = client.get(f"/api/v1/channels/public/webchat/session/{token_a}/messages/")
        assert response.status_code == 200
        assert response.data == []
