"""Database-derived capability checks for knowledge management."""

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceRole

KNOWLEDGE_MANAGEMENT_ROLES = frozenset(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER}
)


class CanManageKnowledge(BasePermission):
    message = "You do not have permission to manage knowledge."

    def has_permission(self, request, view) -> bool:
        membership = getattr(request, "workspace_membership", None)
        return membership is not None and membership.role in KNOWLEDGE_MANAGEMENT_ROLES
