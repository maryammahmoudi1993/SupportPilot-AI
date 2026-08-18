"""Database-derived capability checks for agent configuration and execution."""

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceRole

AGENT_CONFIGURE_ROLES = frozenset(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER}
)
AGENT_RUN_ROLES = frozenset(
    {
        WorkspaceRole.OWNER,
        WorkspaceRole.ADMIN,
        WorkspaceRole.SUPPORT_MANAGER,
        WorkspaceRole.SUPPORT_AGENT,
    }
)


def _role(request) -> str | None:
    membership = getattr(request, "workspace_membership", None)
    return membership.role if membership is not None else None


class CanConfigureAgents(BasePermission):
    """Create/update agent definitions and versions, publish versions."""

    message = "You do not have permission to configure agents."

    def has_permission(self, request, view) -> bool:
        return _role(request) in AGENT_CONFIGURE_ROLES


class CanRunAgents(BasePermission):
    """Start and cancel agent runs."""

    message = "You do not have permission to run agents."

    def has_permission(self, request, view) -> bool:
        return _role(request) in AGENT_RUN_ROLES
