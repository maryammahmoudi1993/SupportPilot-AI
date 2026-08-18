"""Capability-based DRF permissions for the conversation domain.

Viewers are read-only across every conversation and message operation.
Finer-grained rules (manager-only reassignment, agent-must-be-assignee for
status changes) are enforced in ``conversations.services`` because they
depend on record state, not just role.
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


class CanMutateConversations(BasePermission):
    """Any non-viewer role may create conversations, send messages, assign
    (subject to service-layer self-assign rules), and change status
    (subject to service-layer assignment rules)."""

    message = "You do not have permission to modify conversations."

    def has_permission(self, request, view) -> bool:
        membership = _membership(request)
        return membership is not None and membership.role in NON_VIEWER_ROLES
