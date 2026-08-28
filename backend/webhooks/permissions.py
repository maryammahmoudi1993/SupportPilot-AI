"""Database-derived capability checks for webhook endpoint management
(section 40): create/update/disable/rotate requires support_manager or
above — a broader set than integration credential management
(owner/admin only) since a webhook endpoint carries no third-party
provider credential, only this workspace's own outbound signing secret."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceRole

WEBHOOK_MANAGE_ROLES = frozenset(
    {WorkspaceRole.SUPPORT_MANAGER, WorkspaceRole.ADMIN, WorkspaceRole.OWNER}
)


def _role(request) -> str | None:
    membership = getattr(request, "workspace_membership", None)
    return membership.role if membership is not None else None


class CanManageWebhooks(BasePermission):
    """Create/update/disable webhook endpoints, rotate signing secrets.
    Always re-derived from the live ``WorkspaceMembership`` resolved for
    this request (``WorkspaceScopedMixin``) — never a cached/JWT role
    claim (section 40-41)."""

    message = "You do not have permission to manage webhook endpoints."

    def has_permission(self, request, view) -> bool:
        return _role(request) in WEBHOOK_MANAGE_ROLES
