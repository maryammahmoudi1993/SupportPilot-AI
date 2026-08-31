"""Database-derived capability checks for evaluation management and runs."""

from rest_framework.permissions import BasePermission

from workspaces.models import WorkspaceRole

#: Create/edit datasets and cases (section 36).
EVALUATION_MANAGE_ROLES = frozenset(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER}
)
#: Trigger runs, compare, and replay (section 36) — a superset that also
#: includes everyone who can manage evaluation content.
EVALUATION_RUN_ROLES = EVALUATION_MANAGE_ROLES
#: View evaluation data — every workspace member, matching the read access
#: level other reporting/trace surfaces use.
EVALUATION_VIEW_ROLES = frozenset(
    {
        WorkspaceRole.OWNER,
        WorkspaceRole.ADMIN,
        WorkspaceRole.SUPPORT_MANAGER,
        WorkspaceRole.SUPPORT_AGENT,
        WorkspaceRole.VIEWER,
    }
)


def _role(request) -> str | None:
    membership = getattr(request, "workspace_membership", None)
    return membership.role if membership is not None else None


class CanViewEvaluations(BasePermission):
    message = "You do not have permission to view evaluations."

    def has_permission(self, request, view) -> bool:
        return _role(request) in EVALUATION_VIEW_ROLES


class CanManageEvaluations(BasePermission):
    """Create/update evaluation datasets and cases."""

    message = "You do not have permission to manage evaluations."

    def has_permission(self, request, view) -> bool:
        return _role(request) in EVALUATION_MANAGE_ROLES


class CanRunEvaluations(BasePermission):
    """Trigger, cancel, compare, and replay evaluation runs."""

    message = "You do not have permission to run evaluations."

    def has_permission(self, request, view) -> bool:
        return _role(request) in EVALUATION_RUN_ROLES
