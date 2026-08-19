"""Connection-test (health probe) endpoint tests (section 68-69, 141)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from integrations.errors import IntegrationAuthenticationFailedError
from integrations.models import IntegrationConnectionStatus, IntegrationProvider
from integrations.providers.fakes import FakePaymentProvider
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import IntegrationConnectionFactory


def _client(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestConnectionTest:
    def test_success(self, monkeypatch):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.OWNER
        )
        fake = FakePaymentProvider()
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
        response = _client(membership.user).post(
            f"/api/v1/workspaces/{connection.workspace.id}/integrations/{connection.id}/test/"
        )
        assert response.status_code == 200
        assert response.data["ok"] is True
        assert response.data["error_code"] is None

    def test_failure_is_normalized_and_never_mutates_business_state(self, monkeypatch):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.OWNER
        )
        fake = FakePaymentProvider(probe_error=IntegrationAuthenticationFailedError())
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
        response = _client(membership.user).post(
            f"/api/v1/workspaces/{connection.workspace.id}/integrations/{connection.id}/test/"
        )
        assert response.status_code == 200
        assert response.data["ok"] is False
        assert response.data["error_code"] == "integration_authentication_failed"
        assert fake.refund_call_count == 0

    def test_disabled_connection_returns_a_stable_error(self):
        connection = IntegrationConnectionFactory(
            provider=IntegrationProvider.STRIPE, status=IntegrationConnectionStatus.DISABLED
        )
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).post(
            f"/api/v1/workspaces/{connection.workspace.id}/integrations/{connection.id}/test/"
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "integration_disabled"

    def test_requires_manage_permission(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        membership = WorkspaceMembershipFactory(
            workspace=connection.workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        response = _client(membership.user).post(
            f"/api/v1/workspaces/{connection.workspace.id}/integrations/{connection.id}/test/"
        )
        assert response.status_code == 403
