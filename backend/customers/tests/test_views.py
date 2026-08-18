"""Customer API tests: auth, RBAC matrix, filtering, pagination, and
cross-tenant isolation."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import CustomerFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture
def workspace():
    return WorkspaceFactory()


@pytest.mark.django_db
class TestCustomerListCreateView:
    def test_requires_authentication(self, workspace):
        response = _client().get(f"/api/v1/workspaces/{workspace.id}/customers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_can_list_customers(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        CustomerFactory(workspace=workspace)

        response = _client(membership.user).get(f"/api/v1/workspaces/{workspace.id}/customers/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    def test_list_is_paginated(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        for _ in range(3):
            CustomerFactory(workspace=workspace)

        response = _client(membership.user).get(f"/api/v1/workspaces/{workspace.id}/customers/")

        assert "results" in response.data
        assert "count" in response.data

    def test_filters_by_is_active(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        CustomerFactory(workspace=workspace, is_active=True)
        CustomerFactory(workspace=workspace, is_active=False)

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/customers/", {"is_active": "true"}
        )

        assert response.data["count"] == 1

    def test_agent_can_create_customer(self, workspace):
        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/customers/",
            {"first_name": "Jane", "last_name": "Doe"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_viewer_cannot_create_customer(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/customers/",
            {"first_name": "Jane"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_workspace_field_is_not_client_writable(self, workspace):
        other_workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/customers/",
            {"first_name": "Jane", "workspace": str(other_workspace.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        from customers.models import Customer

        created = Customer.objects.get(id=response.data["id"])
        assert created.workspace_id == workspace.id


@pytest.mark.django_db
class TestCustomerDetailView:
    def test_member_can_retrieve_customer(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        customer = CustomerFactory(workspace=workspace)

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/customers/{customer.id}/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(customer.id)

    def test_foreign_customer_returns_404(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        foreign_customer = CustomerFactory(workspace=WorkspaceFactory())

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/customers/{foreign_customer.id}/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_viewer_cannot_update_customer(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        customer = CustomerFactory(workspace=workspace)

        response = _client(membership.user).patch(
            f"/api/v1/workspaces/{workspace.id}/customers/{customer.id}/",
            {"last_name": "Smith"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_agent_can_deactivate_customer(self, workspace):
        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        customer = CustomerFactory(workspace=workspace, is_active=True)

        response = _client(membership.user).patch(
            f"/api/v1/workspaces/{workspace.id}/customers/{customer.id}/",
            {"is_active": False},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_active"] is False


@pytest.mark.django_db
class TestCustomerRbacMatrix:
    @pytest.mark.parametrize(
        "role,can_write",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, True),
            (WorkspaceRole.SUPPORT_AGENT, True),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_write_permission_by_role(self, workspace, role, can_write):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=role)

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/customers/",
            {"first_name": "Test"},
            format="json",
        )

        expected = status.HTTP_201_CREATED if can_write else status.HTTP_403_FORBIDDEN
        assert response.status_code == expected

    @pytest.mark.parametrize(
        "role",
        [
            WorkspaceRole.OWNER,
            WorkspaceRole.ADMIN,
            WorkspaceRole.SUPPORT_MANAGER,
            WorkspaceRole.SUPPORT_AGENT,
            WorkspaceRole.VIEWER,
        ],
    )
    def test_every_role_can_read(self, workspace, role):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=role)
        CustomerFactory(workspace=workspace)

        response = _client(membership.user).get(f"/api/v1/workspaces/{workspace.id}/customers/")

        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestCustomerCrossTenantIsolation:
    def test_member_of_workspace_b_cannot_list_workspace_a_customers(self):
        workspace_a = WorkspaceFactory()
        workspace_b = WorkspaceFactory()
        membership_b = WorkspaceMembershipFactory(workspace=workspace_b, role=WorkspaceRole.OWNER)
        CustomerFactory(workspace=workspace_a)

        response = _client(membership_b.user).get(f"/api/v1/workspaces/{workspace_a.id}/customers/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_member_of_workspace_b_cannot_retrieve_workspace_a_customer(self):
        workspace_a = WorkspaceFactory()
        workspace_b = WorkspaceFactory()
        membership_b = WorkspaceMembershipFactory(workspace=workspace_b, role=WorkspaceRole.OWNER)
        customer_a = CustomerFactory(workspace=workspace_a)

        response = _client(membership_b.user).get(
            f"/api/v1/workspaces/{workspace_a.id}/customers/{customer_a.id}/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_anonymous_gets_401_not_404(self, workspace):
        response = _client().get(f"/api/v1/workspaces/{workspace.id}/customers/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
