"""Selector tests: tenant scoping must exclude cross-tenant/inactive rows."""

import pytest
from django.http import Http404

from workspaces import selectors
from workspaces.models import WorkspaceRole

from .factories import UserFactory, WorkspaceFactory, WorkspaceMembershipFactory


@pytest.mark.django_db
class TestListWorkspacesForUser:
    def test_only_returns_workspaces_with_an_active_membership(self):
        user = UserFactory()
        active_ws = WorkspaceFactory()
        WorkspaceMembershipFactory(workspace=active_ws, user=user, is_active=True)
        inactive_ws = WorkspaceFactory()
        WorkspaceMembershipFactory(workspace=inactive_ws, user=user, is_active=False)
        other_ws = WorkspaceFactory()
        WorkspaceMembershipFactory(workspace=other_ws)

        result = list(selectors.list_workspaces_for_user(user=user))

        assert result == [active_ws]


@pytest.mark.django_db
class TestGetWorkspaceForUserOr404:
    def test_returns_workspace_for_active_member(self):
        user = UserFactory()
        workspace = WorkspaceFactory()
        WorkspaceMembershipFactory(workspace=workspace, user=user)

        assert selectors.get_workspace_for_user_or_404(user=user, workspace_id=workspace.id) == (
            workspace
        )

    def test_raises_404_for_nonexistent_workspace(self):
        user = UserFactory()
        with pytest.raises(Http404):
            selectors.get_workspace_for_user_or_404(
                user=user, workspace_id="00000000-0000-0000-0000-000000000000"
            )

    def test_raises_404_for_workspace_the_user_is_not_a_member_of(self):
        user = UserFactory()
        workspace = WorkspaceFactory()  # no membership created

        with pytest.raises(Http404):
            selectors.get_workspace_for_user_or_404(user=user, workspace_id=workspace.id)

    def test_raises_404_for_inactive_membership(self):
        user = UserFactory()
        workspace = WorkspaceFactory()
        WorkspaceMembershipFactory(workspace=workspace, user=user, is_active=False)

        with pytest.raises(Http404):
            selectors.get_workspace_for_user_or_404(user=user, workspace_id=workspace.id)


@pytest.mark.django_db
class TestGetWorkspaceMemberOr404:
    def test_raises_404_for_membership_in_a_different_workspace(self):
        workspace_a = WorkspaceFactory()
        workspace_b = WorkspaceFactory()
        membership_in_b = WorkspaceMembershipFactory(workspace=workspace_b)

        with pytest.raises(Http404):
            selectors.get_workspace_member_or_404(
                workspace=workspace_a, membership_id=membership_in_b.id
            )

    def test_returns_membership_for_matching_workspace(self):
        workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(workspace=workspace)

        result = selectors.get_workspace_member_or_404(
            workspace=workspace, membership_id=membership.id
        )

        assert result == membership


@pytest.mark.django_db
class TestGetActiveMembership:
    def test_returns_none_when_no_membership_exists(self):
        user = UserFactory()
        workspace = WorkspaceFactory()
        assert selectors.get_active_membership(workspace=workspace, user=user) is None

    def test_returns_none_for_inactive_membership(self):
        user = UserFactory()
        workspace = WorkspaceFactory()
        WorkspaceMembershipFactory(workspace=workspace, user=user, is_active=False)
        assert selectors.get_active_membership(workspace=workspace, user=user) is None

    def test_returns_the_active_membership(self):
        user = UserFactory()
        workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(
            workspace=workspace, user=user, role=WorkspaceRole.ADMIN
        )
        assert selectors.get_active_membership(workspace=workspace, user=user) == membership


@pytest.mark.django_db
class TestGetMembership:
    def test_returns_none_when_no_membership_exists(self):
        assert selectors.get_membership(workspace=WorkspaceFactory(), user=UserFactory()) is None

    def test_returns_membership_regardless_of_active_state(self):
        membership = WorkspaceMembershipFactory(is_active=False)
        result = selectors.get_membership(workspace=membership.workspace, user=membership.user)
        assert result == membership


@pytest.mark.django_db
class TestGetActiveMembershipForWorkspaceIdOrNone:
    def test_returns_none_for_nonexistent_workspace(self):
        user = UserFactory()
        result = selectors.get_active_membership_for_workspace_id_or_none(
            user=user, workspace_id="00000000-0000-0000-0000-000000000000"
        )
        assert result is None

    def test_returns_none_for_inactive_membership(self):
        membership = WorkspaceMembershipFactory(is_active=False)
        result = selectors.get_active_membership_for_workspace_id_or_none(
            user=membership.user, workspace_id=membership.workspace_id
        )
        assert result is None

    def test_returns_the_active_membership(self):
        membership = WorkspaceMembershipFactory()
        result = selectors.get_active_membership_for_workspace_id_or_none(
            user=membership.user, workspace_id=membership.workspace_id
        )
        assert result == membership
