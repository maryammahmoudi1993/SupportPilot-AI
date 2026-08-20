"""Policy configuration is privileged (section 75): only owner/admin may
create, version, or activate a workspace policy. Read access (list/detail)
is any active workspace member — the response never includes anything
unsafe."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceRole

POLICY_MANAGE_ROLES = frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})


class CanManagePolicies(BasePermission):
    message = "You do not have permission to manage workspace policy."

    def has_permission(self, request, view) -> bool:
        membership = getattr(request, "workspace_membership", None)
        return membership is not None and membership.role in POLICY_MANAGE_ROLES
