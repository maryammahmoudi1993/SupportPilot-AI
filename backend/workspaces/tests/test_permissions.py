"""Unit tests for the capability-based role-management helper and DRF
permission primitives."""

import pytest
from rest_framework.test import APIRequestFactory

from workspaces.models import WorkspaceRole
from workspaces.permissions import (
    CanManageMembers,
    CanManageWorkspace,
    IsWorkspaceMember,
    IsWorkspaceOwner,
    can_manage_target_role,
)

from .factories import WorkspaceMembershipFactory


@pytest.mark.parametrize(
    "actor_role,target_role,expected",
    [
        (WorkspaceRole.OWNER, WorkspaceRole.ADMIN, True),
        (WorkspaceRole.OWNER, WorkspaceRole.SUPPORT_MANAGER, True),
        (WorkspaceRole.OWNER, WorkspaceRole.SUPPORT_AGENT, True),
        (WorkspaceRole.OWNER, WorkspaceRole.VIEWER, True),
        (WorkspaceRole.OWNER, WorkspaceRole.OWNER, False),
        (WorkspaceRole.ADMIN, WorkspaceRole.ADMIN, False),
        (WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER, True),
        (WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_AGENT, True),
        (WorkspaceRole.ADMIN, WorkspaceRole.VIEWER, True),
        (WorkspaceRole.ADMIN, WorkspaceRole.OWNER, False),
        (WorkspaceRole.SUPPORT_MANAGER, WorkspaceRole.SUPPORT_AGENT, False),
        (WorkspaceRole.SUPPORT_AGENT, WorkspaceRole.VIEWER, False),
        (WorkspaceRole.VIEWER, WorkspaceRole.VIEWER, False),
    ],
)
def test_can_manage_target_role_matrix(actor_role, target_role, expected):
    assert can_manage_target_role(actor_role=actor_role, target_role=target_role) is expected


@pytest.mark.django_db
class TestPermissionClasses:
    def _request(self, membership=None):
        request = APIRequestFactory().get("/")
        request.workspace_membership = membership
        return request

    def test_is_workspace_member_true_with_membership(self):
        membership = WorkspaceMembershipFactory()
        assert IsWorkspaceMember().has_permission(self._request(membership), None) is True

    def test_is_workspace_member_false_without_membership(self):
        assert IsWorkspaceMember().has_permission(self._request(None), None) is False

    def test_is_workspace_owner_requires_owner_role(self):
        owner = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        admin = WorkspaceMembershipFactory(role=WorkspaceRole.ADMIN)
        assert IsWorkspaceOwner().has_permission(self._request(owner), None) is True
        assert IsWorkspaceOwner().has_permission(self._request(admin), None) is False

    @pytest.mark.parametrize(
        "role,expected",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, False),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_can_manage_workspace(self, role, expected):
        membership = WorkspaceMembershipFactory(role=role)
        assert CanManageWorkspace().has_permission(self._request(membership), None) is expected

    @pytest.mark.parametrize(
        "role,expected",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, False),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_can_manage_members(self, role, expected):
        membership = WorkspaceMembershipFactory(role=role)
        assert CanManageMembers().has_permission(self._request(membership), None) is expected
