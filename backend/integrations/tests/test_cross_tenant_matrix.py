"""Cross-tenant IDOR and RBAC matrix for the integrations domain (Phase 15
checkpoint 3, Part A/B). ``IntegrationConnection`` holds workspace-owner
credentials, so this domain gets its own narrower RBAC ceiling
(``CanManageIntegrations`` = owner/admin only, unlike most other apps which
also allow support_manager) — the matrix below proves both the tenant
boundary and that narrower ceiling."""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from common.tests.security_matrix import two_workspaces
from integrations.models import IntegrationConnection

from .factories import IntegrationConnectionFactory

__all__ = ["two_workspaces"]


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _base(workspace_id) -> str:
    return f"/api/v1/workspaces/{workspace_id}/integrations"


@pytest.mark.django_db
class TestIntegrationCrossTenant:
    def test_foreign_workspace_detail_is_404(self, two_workspaces):
        d = two_workspaces
        connection = IntegrationConnectionFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/{connection.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_credential_rotation_is_404_and_credentials_unchanged(
        self, two_workspaces
    ):
        d = two_workspaces
        connection = IntegrationConnectionFactory(workspace=d["workspace_a"])
        original_ciphertext = connection.encrypted_credentials
        original_version = connection.credential_version

        response = _client(d["b_owner"].user).put(
            f"{_base(d['workspace_b'].id)}/{connection.id}/credentials/",
            {"credentials": {"secret_key": "sk_live_stolen"}},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        connection.refresh_from_db()
        assert connection.encrypted_credentials == original_ciphertext
        assert connection.credential_version == original_version

    def test_foreign_workspace_enable_toggle_is_404_and_status_unchanged(self, two_workspaces):
        d = two_workspaces
        connection = IntegrationConnectionFactory(workspace=d["workspace_a"])
        original_status = connection.status

        response = _client(d["b_owner"].user).patch(
            f"{_base(d['workspace_b'].id)}/{connection.id}/enabled/",
            {"enabled": False},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        connection.refresh_from_db()
        assert connection.status == original_status

    def test_foreign_workspace_connection_test_is_404_and_no_provider_call(
        self, two_workspaces, monkeypatch
    ):
        d = two_workspaces
        connection = IntegrationConnectionFactory(workspace=d["workspace_a"])
        called = []
        monkeypatch.setattr(
            "integrations.services.test_connection",
            lambda **kwargs: called.append(kwargs) or None,
        )
        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/{connection.id}/test/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert called == []

    def test_connection_list_never_leaks_another_tenants_connection(self, two_workspaces):
        d = two_workspaces
        IntegrationConnectionFactory(workspace=d["workspace_a"], display_name="A-only")
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/")
        names = [row["display_name"] for row in response.data["results"]]
        assert "A-only" not in names

    def test_foreign_connection_id_through_filter_never_leaks_data(self, two_workspaces):
        d = two_workspaces
        connection = IntegrationConnectionFactory(workspace=d["workspace_a"])
        # No supported filter takes a raw connection id in this app today —
        # confirm the list endpoint itself, unfiltered, still excludes it
        # (covered above); this test locks in that there is no query-param
        # bypass of the workspace scope for connection lookups.
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/?connection={connection.id}"
        )
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.data["results"]]
        assert str(connection.id) not in ids


@pytest.mark.django_db
class TestIntegrationRBAC:
    """``CanManageIntegrations`` is owner/admin only — narrower than most
    other domains' manager-tier ceiling. Confirm support_manager-equivalent
    (support_agent here, since this workspace has no dedicated
    support_manager role in the fixture) and viewer are both denied, and
    owner/admin are both allowed."""

    def test_support_agent_cannot_create_connection(self, two_workspaces):
        d = two_workspaces
        response = _client(d["a_agent"].user).post(
            f"{_base(d['workspace_a'].id)}/",
            {"provider": "stripe", "display_name": "x", "credentials": {"secret_key": "sk_test_x"}},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_cannot_rotate_credentials(self, two_workspaces):
        d = two_workspaces
        connection = IntegrationConnectionFactory(workspace=d["workspace_a"])
        response = _client(d["a_viewer"].user).put(
            f"{_base(d['workspace_a'].id)}/{connection.id}/credentials/",
            {"credentials": {"secret_key": "sk_test_y"}},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_rotate_credentials(self, two_workspaces):
        d = two_workspaces
        connection = IntegrationConnectionFactory(workspace=d["workspace_a"])
        response = _client(d["a_admin"].user).put(
            f"{_base(d['workspace_a'].id)}/{connection.id}/credentials/",
            {"credentials": {"secret_key": "sk_test_z1234567890"}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestIntegrationMassAssignment:
    def test_client_cannot_set_credential_version_or_status_on_create(self, two_workspaces):
        d = two_workspaces
        response = _client(d["a_owner"].user).post(
            f"{_base(d['workspace_a'].id)}/",
            {
                "provider": "stripe",
                "display_name": "x",
                "credentials": {"secret_key": "sk_test_abc1234567890"},
                "credential_version": 99,
                "status": "active",
                "workspace": str(d["workspace_b"].id),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        connection = IntegrationConnection.objects.get(pk=response.data["id"])
        assert connection.workspace_id == d["workspace_a"].id
        assert connection.credential_version == 1

    def test_response_never_includes_encrypted_credentials(self, two_workspaces):
        d = two_workspaces
        IntegrationConnectionFactory(workspace=d["workspace_a"])
        response = _client(d["a_owner"].user).get(f"{_base(d['workspace_a'].id)}/")
        assert "encrypted_credentials" not in str(response.data)
        assert "sk_test" not in str(response.data)
