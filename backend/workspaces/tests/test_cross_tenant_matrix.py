"""Consolidated cross-tenant regression matrix.

A long-term regression guard: Workspace A / Workspace B / a member of each /
an anonymous client, driven against every Phase-2 workspace-scoped endpoint
with valid IDs from the *wrong* tenant. This is the shape every future
tenant-scoped app should be tested against.
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from workspaces.models import WorkspaceRole

from .factories import UserFactory, WorkspaceFactory, WorkspaceMembershipFactory


@pytest.fixture
def two_workspaces():
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    user_a = UserFactory()
    user_b = UserFactory()
    membership_a = WorkspaceMembershipFactory(
        workspace=workspace_a, user=user_a, role=WorkspaceRole.OWNER
    )
    membership_b = WorkspaceMembershipFactory(
        workspace=workspace_b, user=user_b, role=WorkspaceRole.OWNER
    )
    return {
        "workspace_a": workspace_a,
        "workspace_b": workspace_b,
        "user_a": user_a,
        "user_b": user_b,
        "membership_a": membership_a,
        "membership_b": membership_b,
    }


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestCrossTenantMatrix:
    @pytest.mark.parametrize(
        "build_request",
        [
            lambda d: ("get", f"/api/v1/workspaces/{d['workspace_a'].id}/", None),
            lambda d: (
                "patch",
                f"/api/v1/workspaces/{d['workspace_a'].id}/",
                {"name": "Hijacked"},
            ),
            lambda d: ("get", f"/api/v1/workspaces/{d['workspace_a'].id}/members/", None),
            lambda d: (
                "get",
                f"/api/v1/workspaces/{d['workspace_a'].id}/members/{d['membership_a'].id}/",
                None,
            ),
            lambda d: (
                "delete",
                f"/api/v1/workspaces/{d['workspace_a'].id}/members/{d['membership_a'].id}/",
                None,
            ),
            lambda d: (
                "post",
                f"/api/v1/workspaces/{d['workspace_a'].id}/transfer-ownership/",
                {"membership_id": str(d["membership_a"].id)},
            ),
        ],
    )
    def test_member_of_b_gets_404_on_workspace_a_resources(self, two_workspaces, build_request):
        method, path, payload = build_request(two_workspaces)
        client = _client(two_workspaces["user_b"])

        response = getattr(client, method)(path, payload, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "build_request",
        [
            lambda d: ("get", f"/api/v1/workspaces/{d['workspace_a'].id}/", None),
            lambda d: (
                "patch",
                f"/api/v1/workspaces/{d['workspace_a'].id}/",
                {"name": "Hijacked"},
            ),
            lambda d: ("get", f"/api/v1/workspaces/{d['workspace_a'].id}/members/", None),
            lambda d: (
                "post",
                f"/api/v1/workspaces/{d['workspace_a'].id}/transfer-ownership/",
                {"membership_id": str(d["membership_a"].id)},
            ),
        ],
    )
    def test_anonymous_gets_401_on_workspace_a_resources(self, two_workspaces, build_request):
        method, path, payload = build_request(two_workspaces)

        response = getattr(_client(), method)(path, payload, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_same_workspace_insufficient_role_gets_403(self, two_workspaces):
        viewer = WorkspaceMembershipFactory(
            workspace=two_workspaces["workspace_a"], role=WorkspaceRole.VIEWER
        )

        response = _client(viewer.user).patch(
            f"/api/v1/workspaces/{two_workspaces['workspace_a'].id}/",
            {"name": "Renamed"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_workspace_list_never_leaks_another_tenants_workspace(self, two_workspaces):
        response = _client(two_workspaces["user_b"]).get("/api/v1/workspaces/")
        ids = [w["id"] for w in response.data["results"]]
        assert str(two_workspaces["workspace_a"].id) not in ids
