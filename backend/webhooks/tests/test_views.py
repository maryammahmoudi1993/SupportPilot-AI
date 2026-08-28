"""Webhook endpoint/delivery API: RBAC, tenant isolation, secret-free
responses, and mass-assignment safety (Phase 10 Block 3, section 36-44,
64, 67-68)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from notifications.models import DeliveryChannel
from notifications.services import create_delivery
from webhooks.models import WebhookDelivery, WebhookEndpoint, WebhookEventType
from webhooks.tests.factories import TEST_SECRET, WebhookEndpointFactory, WebhookEventFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace) -> str:
    return f"/api/v1/workspaces/{workspace.id}/webhooks"


@pytest.mark.django_db
class TestEndpointListCreate:
    def test_anonymous_is_401(self):
        membership = WorkspaceMembershipFactory()
        assert _client().get(f"{_base(membership.workspace)}/endpoints/").status_code == 401

    def test_any_member_can_list_but_response_excludes_secret(self):
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).get(f"{_base(membership.workspace)}/endpoints/")
        assert response.status_code == 200
        payload = response.data["results"][0]
        assert "encrypted_signing_secret" not in payload
        assert "signing_secret" not in payload
        assert TEST_SECRET not in str(response.data)
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
    def test_create_requires_manager_or_above(self, role, allowed, monkeypatch):
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
        membership = WorkspaceMembershipFactory(role=role)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/endpoints/",
            data={
                "name": "My hook",
                "url": "https://example.com/hook",
                "subscribed_event_types": [WebhookEventType.APPROVAL_REQUESTED],
            },
            format="json",
        )
        assert (response.status_code == 201) is allowed

    def test_create_returns_secret_exactly_once(self, monkeypatch):
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/endpoints/",
            data={
                "name": "My hook",
                "url": "https://example.com/hook",
                "subscribed_event_types": [WebhookEventType.APPROVAL_REQUESTED],
            },
            format="json",
        )
        assert response.status_code == 201
        assert "signing_secret" in response.data
        secret = response.data["signing_secret"]
        assert len(secret) == 64

        detail = _client(membership.user).get(
            f"{_base(membership.workspace)}/endpoints/{response.data['id']}/"
        )
        assert secret not in str(detail.data)
        assert "signing_secret" not in detail.data

    def test_create_rejects_ssrf_url(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/endpoints/",
            data={
                "name": "My hook",
                "url": "https://127.0.0.1/hook",
                "subscribed_event_types": [WebhookEventType.APPROVAL_REQUESTED],
            },
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "webhook_destination_blocked"

    def test_create_rejects_unknown_event_type(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/endpoints/",
            data={
                "name": "My hook",
                "url": "https://example.com/hook",
                "subscribed_event_types": ["not.a.real.event"],
            },
            format="json",
        )
        assert response.status_code == 400

    def test_create_cannot_set_server_owned_fields(self, monkeypatch):
        """Mass-assignment safety (section 38): the create serializer has
        no fields for status/encrypted secret/created_by/etc. at all — an
        attempt to smuggle one in is rejected by strict schema validation."""
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/endpoints/",
            data={
                "name": "My hook",
                "url": "https://example.com/hook",
                "subscribed_event_types": [WebhookEventType.APPROVAL_REQUESTED],
                "status": "disabled",
                "encrypted_signing_secret": "attacker-value",
                "workspace": "11111111-1111-1111-1111-111111111111",
            },
            format="json",
        )
        assert response.status_code == 201
        endpoint = WebhookEndpoint.objects.get(pk=response.data["id"])
        assert endpoint.status == "active"
        assert endpoint.encrypted_signing_secret != "attacker-value"
        assert endpoint.workspace_id == membership.workspace_id


@pytest.mark.django_db
class TestEndpointDetailAndStatus:
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
    def test_update_requires_manager_or_above(self, role, allowed):
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(workspace=endpoint.workspace, role=role)
        response = _client(membership.user).patch(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/",
            data={"name": "Renamed"},
            format="json",
        )
        assert (response.status_code == 200) is allowed

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
    def test_disable_requires_manager_or_above(self, role, allowed):
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(workspace=endpoint.workspace, role=role)
        response = _client(membership.user).patch(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/status/",
            data={"status": "disabled"},
            format="json",
        )
        assert (response.status_code == 200) is allowed

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
    def test_rotate_secret_requires_manager_or_above(self, role, allowed):
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(workspace=endpoint.workspace, role=role)
        response = _client(membership.user).post(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/rotate-secret/"
        )
        assert (response.status_code == 200) is allowed

    def test_rotate_secret_returns_new_secret_once(self):
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).post(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/rotate-secret/"
        )
        assert response.status_code == 200
        new_secret = response.data["signing_secret"]
        assert new_secret != TEST_SECRET

        detail = _client(membership.user).get(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/"
        )
        assert new_secret not in str(detail.data)

    def test_role_demotion_after_token_issued_denies_mutation(self):
        """Section 41: a stale JWT/session for a since-demoted user must
        not permit rotation — every check re-reads live DB membership."""
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        client = _client(membership.user)

        # Demote in the DB — no new token/session is issued to the client.
        membership.role = WorkspaceRole.SUPPORT_AGENT
        membership.save(update_fields=["role"])

        response = client.post(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/rotate-secret/"
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestTenantIsolation:
    def test_foreign_workspace_endpoint_is_404_on_every_action(self):
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)  # different workspace
        client = _client(membership.user)
        base = f"{_base(membership.workspace)}/endpoints/{endpoint.id}"

        assert client.get(f"{base}/").status_code == 404
        assert client.patch(f"{base}/", data={"name": "x"}, format="json").status_code == 404
        assert (
            client.patch(f"{base}/status/", data={"status": "disabled"}, format="json").status_code
            == 404
        )
        assert client.post(f"{base}/rotate-secret/").status_code == 404

    def test_foreign_workspace_delivery_is_404(self):
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        membership = WorkspaceMembershipFactory()  # different workspace
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/deliveries/{delivery.id}/"
        )
        assert response.status_code == 404

    def test_endpoint_not_leaked_via_error_message(self):
        """A cross-tenant 404 must be indistinguishable from a truly
        nonexistent id — no existence leakage (section 42)."""
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        real_id_response = _client(membership.user).get(
            f"{_base(membership.workspace)}/endpoints/{endpoint.id}/"
        )
        import uuid

        fake_id_response = _client(membership.user).get(
            f"{_base(membership.workspace)}/endpoints/{uuid.uuid4()}/"
        )
        assert real_id_response.status_code == fake_id_response.status_code == 404


@pytest.mark.django_db
class TestDeliveryInspection:
    def test_delivery_detail_exposes_only_safe_fields(self, monkeypatch):
        from notifications.services import claim_delivery, complete_delivery_success

        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(
            workspace=endpoint.workspace, payload_snapshot={"secret_field": "x"}
        )
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        claimed, token = claim_delivery(delivery_id=delivery.id)
        complete_delivery_success(delivery_id=claimed.id, claim_token=token)

        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).get(
            f"{_base(endpoint.workspace)}/deliveries/{delivery.id}/"
        )
        assert response.status_code == 200
        assert response.data["status"] == "delivered"
        assert TEST_SECRET not in str(response.data)
        assert "signing_secret" not in response.data
        assert "X-SupportPilot-Signature" not in str(response.data)

    def test_delivery_list_returns_paginated_results(self):
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).get(f"{_base(endpoint.workspace)}/deliveries/")
        assert response.status_code == 200
        assert response.data["results"][0]["delivery_id"] == str(delivery.id)

    def test_foreign_delivery_detail_is_404(self):
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        import uuid

        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).get(
            f"{_base(endpoint.workspace)}/deliveries/{uuid.uuid4()}/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestUpdateValidation:
    def test_update_with_invalid_url_returns_safe_400(self):
        endpoint = WebhookEndpointFactory()
        membership = WorkspaceMembershipFactory(
            workspace=endpoint.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).patch(
            f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/",
            data={"url": "ftp://example.com"},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "webhook_invalid_url"


class TestSwaggerFakeView:
    """drf-spectacular introspects views with ``swagger_fake_view=True`` set
    and no real workspace resolved — every list view must degrade to an
    empty queryset rather than erroring during schema generation."""

    def test_endpoint_list_view_returns_empty_queryset_for_schema_generation(self):
        from webhooks.views import WebhookEndpointListCreateView

        view = WebhookEndpointListCreateView()
        view.swagger_fake_view = True
        assert list(view.get_queryset()) == []

    def test_delivery_list_view_returns_empty_queryset_for_schema_generation(self):
        from webhooks.views import WebhookDeliveryListView

        view = WebhookDeliveryListView()
        view.swagger_fake_view = True
        assert list(view.get_queryset()) == []


class TestOpenAPISchemaAccuracy:
    """Phase 10 Block 6 regression: drf-spectacular resolves a plain
    (non-ViewSet) view's per-operation schema via
    ``getattr(view, method.lower())`` — the literal HTTP-verb method, not
    the semantic CRUD action name. A ``@extend_schema`` on ``create()``
    alone is silently ignored for a ``ListCreateAPIView``'s POST, because
    DRF's own dispatch there is the inherited, undecorated ``post()``
    (which only delegates to ``create()``) — the generated schema then
    falls back to documenting the *request* shape as the response too,
    silently under-documenting the real one-time ``signing_secret``
    exposure. This failed before the fix in this exact way."""

    def test_endpoint_create_response_schema_documents_the_actual_response_shape(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        create_op = schema["paths"]["/api/v1/workspaces/{workspace_id}/webhooks/endpoints/"]["post"]
        response_ref = create_op["responses"]["201"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        component_name = response_ref.rsplit("/", 1)[-1]
        component = schema["components"]["schemas"][component_name]
        assert "signing_secret" in component["properties"]
        assert "id" in component["properties"]
        assert "status" in component["properties"]
        # Not the bare request-serializer shape (name/url/subscribed_event_types
        # only) — the actual documented bug this regression guards against.
        assert component_name != "WebhookEndpointCreate"
