"""Database-derived capability checks for tool configuration and inspection."""

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceRole

TOOL_CONFIGURE_ROLES = frozenset(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER}
)


def _role(request) -> str | None:
    membership = getattr(request, "workspace_membership", None)
    return membership.role if membership is not None else None


class CanConfigureTools(BasePermission):
    """Bind/unbind tools on a draft agent version."""

    message = "You do not have permission to configure agent tools."

    def has_permission(self, request, view) -> bool:
        return _role(request) in TOOL_CONFIGURE_ROLES
