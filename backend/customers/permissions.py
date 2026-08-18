"""Capability-based DRF permissions for the customer domain.

Mirrors ``workspaces.permissions``: every check re-derives the caller's role
from ``request.workspace_membership``, set by ``WorkspaceScopedMixin`` after
resolving the workspace through a tenant-scoped selector.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceMembership, WorkspaceRole

#: Every role except viewer may create/update operational customer details.
CUSTOMER_WRITE_ROLES = frozenset(
    {
        WorkspaceRole.OWNER,
        WorkspaceRole.ADMIN,
        WorkspaceRole.SUPPORT_MANAGER,
        WorkspaceRole.SUPPORT_AGENT,
    }
)


def _membership(request) -> WorkspaceMembership | None:
    return getattr(request, "workspace_membership", None)


class CanWriteCustomers(BasePermission):
    message = "You do not have permission to modify customers."

    def has_permission(self, request, view) -> bool:
        membership = _membership(request)
        return membership is not None and membership.role in CUSTOMER_WRITE_ROLES
