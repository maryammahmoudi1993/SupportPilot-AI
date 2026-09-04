"""Cross-tenant IDOR and nested-IDOR matrix for the channel_ingress staff
API (Phase 15 checkpoint 3, Part A). The public ingress surface
(``InboundWebhookView``, web-chat bootstrap/messages) already has dedicated
existence-oracle and signature coverage in ``test_security.py``/
``test_views.py`` (``test_unknown_endpoint_id_404s_indistinguishably_from_disabled``,
``test_disabled_endpoint_404s``) — not duplicated here."""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from agents.tests.factories import PublishedAgentVersionFactory
from common.tests.security_matrix import two_workspaces
from integrations.tests.factories import IntegrationConnectionFactory

from .factories import ChannelEndpointFactory, InboundChannelEventFactory

__all__ = ["two_workspaces"]


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _base(workspace_id) -> str:
    return f"/api/v1/workspaces/{workspace_id}/channels"


@pytest.mark.django_db
class TestChannelEndpointCrossTenant:
    def test_foreign_workspace_endpoint_detail_is_404(self, two_workspaces):
        d = two_workspaces
        endpoint = ChannelEndpointFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/endpoints/{endpoint.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_status_toggle_is_404_and_unchanged(self, two_workspaces):
        d = two_workspaces
        endpoint = ChannelEndpointFactory(workspace=d["workspace_a"])
        original_status = endpoint.status
        response = _client(d["b_owner"].user).patch(
            f"{_base(d['workspace_b'].id)}/endpoints/{endpoint.id}/status/",
            {"status": "disabled"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        endpoint.refresh_from_db()
        assert endpoint.status == original_status

    def test_foreign_workspace_rotate_secret_is_404_and_secret_unchanged(self, two_workspaces):
        d = two_workspaces
        endpoint = ChannelEndpointFactory(workspace=d["workspace_a"])
        original_secret = endpoint.encrypted_signing_secret
        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/endpoints/{endpoint.id}/rotate-secret/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        endpoint.refresh_from_db()
        assert endpoint.encrypted_signing_secret == original_secret

    def test_creating_an_endpoint_against_a_foreign_workspaces_agent_version_is_rejected(
        self, two_workspaces
    ):
        d = two_workspaces
        from channel_ingress.models import ChannelEndpoint

        version_a = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/endpoints/",
            {
                "channel": "generic_webhook",
                "name": "Smuggled endpoint",
                "agent_version_id": str(version_a.id),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not ChannelEndpoint.objects.filter(
            workspace=d["workspace_b"], name="Smuggled endpoint"
        ).exists()

    def test_creating_an_endpoint_against_a_foreign_workspaces_integration_connection_is_rejected(
        self, two_workspaces
    ):
        d = two_workspaces
        version_b = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_b"])
        connection_a = IntegrationConnectionFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/endpoints/",
            {
                "channel": "generic_webhook",
                "name": "Smuggled connection endpoint",
                "agent_version_id": str(version_b.id),
                "integration_connection_id": str(connection_a.id),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_endpoint_list_never_leaks_another_tenants_endpoint(self, two_workspaces):
        d = two_workspaces
        ChannelEndpointFactory(workspace=d["workspace_a"], name="A-only")
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/endpoints/")
        names = [row["name"] for row in response.data["results"]]
        assert "A-only" not in names

    def test_response_never_includes_signing_secret_ciphertext(self, two_workspaces):
        d = two_workspaces
        ChannelEndpointFactory(workspace=d["workspace_a"])
        response = _client(d["a_owner"].user).get(f"{_base(d['workspace_a'].id)}/endpoints/")
        assert "encrypted_signing_secret" not in str(response.data)


@pytest.mark.django_db
class TestInboundChannelEventNestedIDOR:
    def test_event_from_a_foreign_endpoint_is_404(self, two_workspaces):
        d = two_workspaces
        endpoint_a = ChannelEndpointFactory(workspace=d["workspace_a"])
        event_a = InboundChannelEventFactory(endpoint=endpoint_a, workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/events/{event_a.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_event_list_never_leaks_another_tenants_event(self, two_workspaces):
        d = two_workspaces
        endpoint_a = ChannelEndpointFactory(workspace=d["workspace_a"])
        InboundChannelEventFactory(
            endpoint=endpoint_a, workspace=d["workspace_a"], external_identity="a-only@example.com"
        )
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/events/")
        identities = [row["external_identity"] for row in response.data["results"]]
        assert "a-only@example.com" not in identities


@pytest.mark.django_db
class TestChannelRBAC:
    def test_support_agent_cannot_rotate_secret_or_change_status(self, two_workspaces):
        d = two_workspaces
        endpoint = ChannelEndpointFactory(workspace=d["workspace_a"])

        rotate = _client(d["a_agent"].user).post(
            f"{_base(d['workspace_a'].id)}/endpoints/{endpoint.id}/rotate-secret/"
        )
        assert rotate.status_code == status.HTTP_403_FORBIDDEN

        status_change = _client(d["a_agent"].user).patch(
            f"{_base(d['workspace_a'].id)}/endpoints/{endpoint.id}/status/",
            {"status": "disabled"},
            format="json",
        )
        assert status_change.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_can_read_endpoint_list(self, two_workspaces):
        d = two_workspaces
        ChannelEndpointFactory(workspace=d["workspace_a"])
        response = _client(d["a_viewer"].user).get(f"{_base(d['workspace_a'].id)}/endpoints/")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestChannelMassAssignment:
    def test_client_cannot_set_status_or_workspace_via_update_serializer(self, two_workspaces):
        d = two_workspaces
        endpoint = ChannelEndpointFactory(workspace=d["workspace_a"])
        original_status = endpoint.status
        response = _client(d["a_owner"].user).patch(
            f"{_base(d['workspace_a'].id)}/endpoints/{endpoint.id}/",
            {"name": "Renamed", "status": "disabled", "workspace": str(d["workspace_b"].id)},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        endpoint.refresh_from_db()
        assert endpoint.name == "Renamed"
        assert endpoint.status == original_status
        assert endpoint.workspace_id == d["workspace_a"].id
