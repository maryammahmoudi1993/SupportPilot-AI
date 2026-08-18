"""API tests for workspace and membership endpoints: the authorization
matrix, cross-tenant isolation, and immediate revocation."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from workspaces.models import WorkspaceMembership, WorkspaceRole

from .factories import UserFactory, WorkspaceFactory, WorkspaceMembershipFactory


def _client_for(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestWorkspaceListCreate:
    def test_list_requires_authentication(self):
        response = _client_for().get("/api/v1/workspaces/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_only_contains_callers_own_memberships(self):
        user = UserFactory()
        my_ws = WorkspaceFactory()
        WorkspaceMembershipFactory(workspace=my_ws, user=user)
        WorkspaceMembershipFactory()  # unrelated workspace/user

        response = _client_for(user).get("/api/v1/workspaces/")

        assert response.status_code == status.HTTP_200_OK
        ids = [w["id"] for w in response.data["results"]]
        assert ids == [str(my_ws.id)]

    def test_create_makes_creator_the_owner(self):
        user = UserFactory()

        response = _client_for(user).post("/api/v1/workspaces/", {"name": "Acme"})

        assert response.status_code == status.HTTP_201_CREATED
        membership = WorkspaceMembership.objects.get(workspace_id=response.data["id"], user=user)
        assert membership.role == WorkspaceRole.OWNER

    def test_create_rejects_blank_name(self):
        user = UserFactory()
        response = _client_for(user).post("/api/v1/workspaces/", {"name": "   "})
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestWorkspaceDetail:
    def test_anonymous_gets_401(self):
        workspace = WorkspaceFactory()
        response = _client_for().get(f"/api/v1/workspaces/{workspace.id}/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_can_view(self):
        membership = WorkspaceMembershipFactory()
        response = _client_for(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/"
        )
        assert response.status_code == status.HTTP_200_OK

    def test_cross_workspace_detail_is_404(self):
        outsider = UserFactory()
        workspace = WorkspaceFactory()
        response = _client_for(outsider).get(f"/api/v1/workspaces/{workspace.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_nonexistent_workspace_is_404(self):
        user = UserFactory()
        response = _client_for(user).get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
    def test_owner_and_admin_can_update(self, role):
        membership = WorkspaceMembershipFactory(role=role)
        response = _client_for(membership.user).patch(
            f"/api/v1/workspaces/{membership.workspace.id}/", {"name": "Renamed"}
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Renamed"

    @pytest.mark.parametrize(
        "role",
        [WorkspaceRole.SUPPORT_MANAGER, WorkspaceRole.SUPPORT_AGENT, WorkspaceRole.VIEWER],
    )
    def test_lower_roles_cannot_update(self, role):
        membership = WorkspaceMembershipFactory(role=role)
        response = _client_for(membership.user).patch(
            f"/api/v1/workspaces/{membership.workspace.id}/", {"name": "Renamed"}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_workspace_update_is_404(self):
        outsider = UserFactory()
        workspace = WorkspaceFactory()
        response = _client_for(outsider).patch(
            f"/api/v1/workspaces/{workspace.id}/", {"name": "Hijacked"}
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestWorkspaceMemberList:
    def test_anonymous_gets_401(self):
        workspace = WorkspaceFactory()
        response = _client_for().get(f"/api/v1/workspaces/{workspace.id}/members/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

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
    def test_every_role_can_list_members(self, role):
        membership = WorkspaceMembershipFactory(role=role)
        response = _client_for(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/members/"
        )
        assert response.status_code == status.HTTP_200_OK

    def test_cross_workspace_member_list_is_404(self):
        outsider = UserFactory()
        workspace = WorkspaceFactory()
        response = _client_for(outsider).get(f"/api/v1/workspaces/{workspace.id}/members/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_owner_adds_member(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        target = UserFactory()

        response = _client_for(owner_membership.user).post(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/members/",
            {"email": target.email, "role": WorkspaceRole.SUPPORT_AGENT},
        )
        assert response.status_code == status.HTTP_201_CREATED

    @pytest.mark.parametrize(
        "role",
        [WorkspaceRole.SUPPORT_MANAGER, WorkspaceRole.SUPPORT_AGENT, WorkspaceRole.VIEWER],
    )
    def test_non_admin_roles_cannot_add_members(self, role):
        membership = WorkspaceMembershipFactory(role=role)
        target = UserFactory()

        response = _client_for(membership.user).post(
            f"/api/v1/workspaces/{membership.workspace.id}/members/",
            {"email": target.email, "role": WorkspaceRole.VIEWER},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_cannot_add_admin_via_api(self):
        admin_membership = WorkspaceMembershipFactory(role=WorkspaceRole.ADMIN)
        target = UserFactory()

        response = _client_for(admin_membership.user).post(
            f"/api/v1/workspaces/{admin_membership.workspace.id}/members/",
            {"email": target.email, "role": WorkspaceRole.ADMIN},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_cannot_add_owner_role_via_api(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        target = UserFactory()

        response = _client_for(owner_membership.user).post(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/members/",
            {"email": target.email, "role": WorkspaceRole.OWNER},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestWorkspaceMemberDetail:
    def test_cross_workspace_membership_id_is_404(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        foreign_membership = WorkspaceMembershipFactory()

        response = _client_for(owner_membership.user).patch(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/members/{foreign_membership.id}/",
            {"role": WorkspaceRole.VIEWER},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_owner_changes_role(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(
            workspace=owner_membership.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )

        response = _client_for(owner_membership.user).patch(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/members/{target.id}/",
            {"role": WorkspaceRole.SUPPORT_MANAGER},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["role"] == WorkspaceRole.SUPPORT_MANAGER

    def test_owner_removes_member(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(
            workspace=owner_membership.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )

        response = _client_for(owner_membership.user).delete(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/members/{target.id}/"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        target.refresh_from_db()
        assert target.is_active is False

    def test_removed_member_immediately_loses_access_despite_valid_session(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(
            workspace=owner_membership.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        target_client = _client_for(target.user)

        # Sanity: access works before removal.
        before = target_client.get(f"/api/v1/workspaces/{owner_membership.workspace.id}/")
        assert before.status_code == status.HTTP_200_OK

        _client_for(owner_membership.user).delete(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/members/{target.id}/"
        )

        # Same authenticated identity, no new login/token — access is denied
        # immediately because authorization is re-derived from the database.
        after = target_client.get(f"/api/v1/workspaces/{owner_membership.workspace.id}/")
        assert after.status_code == status.HTTP_404_NOT_FOUND

    def test_demoted_admin_immediately_loses_admin_capability(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        admin_membership = WorkspaceMembershipFactory(
            workspace=owner_membership.workspace, role=WorkspaceRole.ADMIN
        )
        admin_client = _client_for(admin_membership.user)

        before = admin_client.patch(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/",
            {"name": "Still Admin"},
        )
        assert before.status_code == status.HTTP_200_OK

        _client_for(owner_membership.user).patch(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/members/{admin_membership.id}/",
            {"role": WorkspaceRole.SUPPORT_AGENT},
        )

        after = admin_client.patch(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/",
            {"name": "No Longer Admin"},
        )
        assert after.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_cannot_remove_owner_via_api(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        admin_membership = WorkspaceMembershipFactory(
            workspace=owner_membership.workspace, role=WorkspaceRole.ADMIN
        )

        response = _client_for(admin_membership.user).delete(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/members/{owner_membership.id}/"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestOwnershipTransfer:
    def test_owner_transfers_ownership(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        target = WorkspaceMembershipFactory(
            workspace=owner_membership.workspace, role=WorkspaceRole.ADMIN
        )

        response = _client_for(owner_membership.user).post(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/transfer-ownership/",
            {"membership_id": str(target.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["role"] == WorkspaceRole.OWNER

    @pytest.mark.parametrize(
        "role",
        [WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER, WorkspaceRole.SUPPORT_AGENT],
    )
    def test_non_owner_roles_cannot_transfer(self, role):
        membership = WorkspaceMembershipFactory(role=role)
        other = WorkspaceMembershipFactory(workspace=membership.workspace)

        response = _client_for(membership.user).post(
            f"/api/v1/workspaces/{membership.workspace.id}/transfer-ownership/",
            {"membership_id": str(other.id)},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_transfer_target_from_another_workspace_is_rejected(self):
        owner_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        foreign = WorkspaceMembershipFactory()

        response = _client_for(owner_membership.user).post(
            f"/api/v1/workspaces/{owner_membership.workspace.id}/transfer-ownership/",
            {"membership_id": str(foreign.id)},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
