"""Integration connection management API: RBAC, tenant isolation, and
secret-free responses (section 64-69, 87, 102-103, 107-108)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from integrations.models import IntegrationConnectionStatus, IntegrationProvider
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import IntegrationConnectionFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace) -> str:
    return f"/api/v1/workspaces/{workspace.id}/integrations"


@pytest.mark.django_db
class TestListCreate:
    def test_anonymous_is_401(self):
        membership = WorkspaceMembershipFactory()
        assert _client().get(f"{_base(membership.workspace)}/").status_code == 401

    def test_any_member_can_list_but_response_excludes_secrets(self):
        connection = IntegrationConnectionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).get(f"{_base(membership.workspace)}/")
        assert response.status_code == 200
        payload = response.data["results"][0]
        assert "encrypted_credentials" not in payload
        assert "sk_test" not in str(payload)
        assert payload["credentials_configured"] is True

    @pytest.mark.parametrize(
        "role,allowed",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, False),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_create_requires_owner_or_admin(self, role, allowed):
        membership = WorkspaceMembershipFactory(role=role)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/",
            data={
                "provider": IntegrationProvider.STRIPE,
                "environment": "test",
                "credentials": {"secret_key": "sk_test_abc123"},
            },
            format="json",
        )
        assert (response.status_code == 201) is allowed

    def test_created_connection_response_never_includes_the_secret_key(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/",
            data={
                "provider": IntegrationProvider.STRIPE,
                "environment": "test",
                "credentials": {"secret_key": "sk_test_super_secret_value"},
            },
            format="json",
        )
        assert response.status_code == 201
        assert "sk_test_super_secret_value" not in str(response.data)
        assert "secret_key" not in response.data

    def test_oversized_credentials_payload_is_rejected(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/",
            data={
                "provider": IntegrationProvider.STRIPE,
                "environment": "test",
                "credentials": {"secret_key": "sk_test_" + "x" * 9000},
            },
            format="json",
        )
        assert response.status_code == 400

    def test_mass_assignment_of_server_owned_fields_is_ignored(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/",
            data={
                "provider": IntegrationProvider.STRIPE,
                "environment": "test",
                "credentials": {"secret_key": "sk_test_abc123"},
                "credential_version": 999,
                "status": "active",
                "last_success_at": "2020-01-01T00:00:00Z",
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["credential_version"] == 1


@pytest.mark.django_db
class TestCreateValidationError:
    def test_invalid_credentials_returns_a_normalized_error(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/",
            data={
                "provider": IntegrationProvider.STRIPE,
                "environment": "test",
                "credentials": {"not_secret_key": "x"},
            },
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "integration_configuration_error"


@pytest.mark.django_db
class TestDetailView:
    def test_get_detail(self):
        connection = IntegrationConnectionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).get(f"{_base(connection.workspace)}/{connection.id}/")
        assert response.status_code == 200
        assert response.data["id"] == str(connection.id)

    def test_patch_updates_display_name(self):
        connection = IntegrationConnectionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).patch(
            f"{_base(connection.workspace)}/{connection.id}/",
            data={"display_name": "Renamed"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["display_name"] == "Renamed"

    def test_patch_requires_manage_permission(self):
        connection = IntegrationConnectionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        response = _client(membership.user).patch(
            f"{_base(connection.workspace)}/{connection.id}/",
            data={"display_name": "Renamed"},
            format="json",
        )
        assert response.status_code == 403

    def test_patch_invalid_configuration_returns_a_normalized_error(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).patch(
            f"{_base(connection.workspace)}/{connection.id}/",
            data={"configuration": {"not_a_real_field": True}},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "integration_configuration_error"


@pytest.mark.django_db
class TestCredentialsAndEnableDisable:
    def test_rotate_requires_owner_or_admin(self):
        connection = IntegrationConnectionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        response = _client(membership.user).put(
            f"{_base(connection.workspace)}/{connection.id}/credentials/",
            data={"credentials": {"secret_key": "sk_test_new"}},
            format="json",
        )
        assert response.status_code == 403

    def test_rotate_response_never_returns_old_or_new_plaintext(self):
        connection = IntegrationConnectionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).put(
            f"{_base(connection.workspace)}/{connection.id}/credentials/",
            data={"credentials": {"secret_key": "sk_test_brand_new"}},
            format="json",
        )
        assert response.status_code == 200
        assert "sk_test_brand_new" not in str(response.data)
        assert response.data["credential_version"] == 2

    def test_disable_then_enable(self):
        connection = IntegrationConnectionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.ADMIN
        )
        client = _client(membership.user)
        response = client.patch(
            f"{_base(connection.workspace)}/{connection.id}/enabled/",
            data={"enabled": False},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["status"] == IntegrationConnectionStatus.DISABLED

        response = client.patch(
            f"{_base(connection.workspace)}/{connection.id}/enabled/",
            data={"enabled": True},
            format="json",
        )
        assert response.data["status"] == IntegrationConnectionStatus.ACTIVE


@pytest.mark.django_db
class TestTenantIsolation:
    def test_foreign_workspace_connection_is_404_not_403(self):
        connection = IntegrationConnectionFactory()
        other_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(other_membership.user).get(
            f"{_base(other_membership.workspace)}/{connection.id}/"
        )
        assert response.status_code == 404

    def test_cannot_rotate_credentials_of_a_foreign_workspace_connection(self):
        connection = IntegrationConnectionFactory()
        other_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(other_membership.user).put(
            f"{_base(other_membership.workspace)}/{connection.id}/credentials/",
            data={"credentials": {"secret_key": "sk_test_x"}},
            format="json",
        )
        assert response.status_code == 404
        connection.refresh_from_db()
        assert connection.credential_version == 1

    def test_immediate_role_demotion_blocks_the_next_manage_request(self):
        connection = IntegrationConnectionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.ADMIN
        )
        client = _client(membership.user)
        assert (
            client.patch(
                f"{_base(connection.workspace)}/{connection.id}/enabled/",
                data={"enabled": False},
                format="json",
            ).status_code
            == 200
        )
        membership.role = WorkspaceRole.SUPPORT_AGENT
        membership.save(update_fields=["role"])
        response = client.patch(
            f"{_base(connection.workspace)}/{connection.id}/enabled/",
            data={"enabled": True},
            format="json",
        )
        assert response.status_code == 403
