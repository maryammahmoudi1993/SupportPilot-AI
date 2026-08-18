"""Capability-based DRF permissions for the ticket domain.

Viewers are read-only. Finer-grained rules (manager-only reassignment, an
agent may only mutate a ticket assigned to them) are enforced in
``tickets.services`` because they depend on record state, not just role.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceMembership, WorkspaceRole

NON_VIEWER_ROLES = frozenset(
    {
        WorkspaceRole.OWNER,
        WorkspaceRole.ADMIN,
        WorkspaceRole.SUPPORT_MANAGER,
        WorkspaceRole.SUPPORT_AGENT,
    }
)


def _membership(request) -> WorkspaceMembership | None:
    return getattr(request, "workspace_membership", None)


class CanMutateTickets(BasePermission):
    message = "You do not have permission to modify tickets."

    def has_permission(self, request, view) -> bool:
        membership = _membership(request)
        return membership is not None and membership.role in NON_VIEWER_ROLES
