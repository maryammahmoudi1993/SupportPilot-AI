"""Consolidated cross-tenant regression matrix for the customer domain."""

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
def two_workspaces():
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    membership_a = WorkspaceMembershipFactory(workspace=workspace_a, role=WorkspaceRole.OWNER)
    membership_b = WorkspaceMembershipFactory(workspace=workspace_b, role=WorkspaceRole.OWNER)
    customer_a = CustomerFactory(workspace=workspace_a)
    return {
        "workspace_a": workspace_a,
        "workspace_b": workspace_b,
        "membership_a": membership_a,
        "membership_b": membership_b,
        "customer_a": customer_a,
    }


@pytest.mark.django_db
class TestCustomerCrossTenantMatrix:
    @pytest.mark.parametrize(
        "build_request",
        [
            lambda d: ("get", f"/api/v1/workspaces/{d['workspace_a'].id}/customers/", None),
            lambda d: (
                "get",
                f"/api/v1/workspaces/{d['workspace_a'].id}/customers/{d['customer_a'].id}/",
                None,
            ),
            lambda d: (
                "patch",
                f"/api/v1/workspaces/{d['workspace_a'].id}/customers/{d['customer_a'].id}/",
                {"last_name": "Hijacked"},
            ),
        ],
    )
    def test_member_of_b_gets_404_on_workspace_a_customers(self, two_workspaces, build_request):
        method, path, payload = build_request(two_workspaces)
        response = getattr(_client(two_workspaces["membership_b"].user), method)(
            path, payload, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_workspace_b_search_never_leaks_workspace_a_customer(self, two_workspaces):
        response = _client(two_workspaces["membership_b"].user).get(
            f"/api/v1/workspaces/{two_workspaces['workspace_b'].id}/customers/",
            {"search": two_workspaces["customer_a"].display_name or "x"},
        )
        ids = [c["id"] for c in response.data["results"]]
        assert str(two_workspaces["customer_a"].id) not in ids

    def test_anonymous_gets_401(self, two_workspaces):
        response = _client().get(
            f"/api/v1/workspaces/{two_workspaces['workspace_a'].id}/customers/"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
