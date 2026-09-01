"""Database-derived capability checks for channel endpoint management
(section 44) — mirrors ``webhooks.permissions.CanManageWebhooks`` exactly:
support_manager or above may create/update/disable an endpoint or rotate its
signing secret."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceRole

CHANNEL_MANAGE_ROLES = frozenset(
    {WorkspaceRole.SUPPORT_MANAGER, WorkspaceRole.ADMIN, WorkspaceRole.OWNER}
)


def _role(request) -> str | None:
    membership = getattr(request, "workspace_membership", None)
    return membership.role if membership is not None else None


class CanManageChannels(BasePermission):
    """Create/update/disable channel endpoints, rotate signing secrets.
    Always re-derived from the live ``WorkspaceMembership`` resolved for
    this request (``WorkspaceScopedMixin``) — never a cached/JWT role
    claim."""

    message = "You do not have permission to manage channel endpoints."

    def has_permission(self, request, view) -> bool:
        return _role(request) in CHANNEL_MANAGE_ROLES
