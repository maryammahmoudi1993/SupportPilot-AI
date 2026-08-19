"""Database-derived capability checks for integration connection management
(section 65-66): a support agent may never submit or view provider
credentials — only owner/admin manage connections, mirroring
``workspaces.permissions.CanManageWorkspace``."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceRole

INTEGRATION_MANAGE_ROLES = frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})


def _role(request) -> str | None:
    membership = getattr(request, "workspace_membership", None)
    return membership.role if membership is not None else None


class CanManageIntegrations(BasePermission):
    """Create/update connections, rotate credentials, enable/disable, test."""

    message = "You do not have permission to manage integration connections."

    def has_permission(self, request, view) -> bool:
        return _role(request) in INTEGRATION_MANAGE_ROLES
