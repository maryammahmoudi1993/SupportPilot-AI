"""Reusable, capability-based DRF permission primitives for workspace tenancy.

Every check here re-derives the caller's role from the database on every
request via ``request.workspace_membership`` (set by the view after resolving
the workspace through a tenant-scoped selector). Nothing here trusts a
client-supplied role, header, or JWT claim. This is what makes role changes
and removals take effect immediately even while an access token remains
valid.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from .models import WorkspaceMembership, WorkspaceRole

MEMBER_MANAGEMENT_ROLES = frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})
WORKSPACE_SETTINGS_ROLES = frozenset({WorkspaceRole.OWNER, WorkspaceRole.ADMIN})


def _membership(request) -> WorkspaceMembership | None:
    return getattr(request, "workspace_membership", None)


class IsWorkspaceMember(BasePermission):
    """Caller has *some* active membership in the request's workspace.

    Views using this permission must set ``request.workspace_membership``
    (typically in ``initial()``/``get_object()``) after resolving the
    workspace via a tenant-scoped selector, before this permission runs.
    """

    message = "You are not a member of this workspace."

    def has_permission(self, request, view) -> bool:
        return _membership(request) is not None


class IsWorkspaceOwner(BasePermission):
    message = "Only the workspace owner may perform this action."

    def has_permission(self, request, view) -> bool:
        membership = _membership(request)
        return membership is not None and membership.role == WorkspaceRole.OWNER


class CanManageWorkspace(BasePermission):
    """Owner/admin: workspace settings (name, etc.)."""

    message = "You do not have permission to manage this workspace."

    def has_permission(self, request, view) -> bool:
        membership = _membership(request)
        return membership is not None and membership.role in WORKSPACE_SETTINGS_ROLES


class CanManageMembers(BasePermission):
    """Owner/admin: add/remove/change-role for members below their own rank."""

    message = "You do not have permission to manage workspace members."

    def has_permission(self, request, view) -> bool:
        membership = _membership(request)
        return membership is not None and membership.role in MEMBER_MANAGEMENT_ROLES


def can_manage_target_role(*, actor_role: str, target_role: str) -> bool:
    """Explicit capability check for whether ``actor_role`` may add/edit a
    membership currently or prospectively holding ``target_role``.

    Deliberately not a numeric/hierarchical comparison, per the RBAC rules:
    - owner may manage any non-owner role, including admin.
    - admin may manage only roles strictly below admin.
    - nobody may use this path to create or modify an owner (ownership
      transfer is a dedicated service).
    """
    if target_role == WorkspaceRole.OWNER:
        return False
    if actor_role == WorkspaceRole.OWNER:
        return True
    if actor_role == WorkspaceRole.ADMIN:
        return target_role != WorkspaceRole.ADMIN
    return False
