"""Workspace and membership mutation services.

Views stay thin: they resolve tenant-scoped objects via selectors, check
permissions, and delegate every state transition here. Serializers validate
request *shape*; they never own transactional business rules.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from common.exceptions import ConflictError

from .models import Workspace, WorkspaceMembership, WorkspaceRole
from .permissions import can_manage_target_role


def _normalize_name(name: str) -> str:
    normalized = " ".join((name or "").split())
    if not normalized:
        raise ValidationError({"name": "Workspace name must not be blank."})
    return normalized


@transaction.atomic
def create_workspace(*, actor: User, name: str, request_id: str | None = None) -> Workspace:
    """Create a workspace and its owner membership atomically. If either the
    membership or the audit event fails to persist, the whole operation rolls
    back — no partially-created tenant is ever observable."""
    workspace = Workspace.objects.create(name=_normalize_name(name))
    WorkspaceMembership.objects.create(
        workspace=workspace, user=actor, role=WorkspaceRole.OWNER, is_active=True
    )
    record_event(
        action=AuditAction.WORKSPACE_CREATED,
        target_type="workspace",
        target_id=workspace.id,
        actor=actor,
        workspace=workspace,
        metadata={"name": workspace.name},
        request_id=request_id,
    )
    return workspace


@transaction.atomic
def update_workspace(
    *,
    workspace: Workspace,
    actor: User,
    name: str | None = None,
    request_id: str | None = None,
) -> Workspace:
    """Update mutable workspace settings. Caller-level permission (owner/admin)
    must already be enforced by the view before calling this."""
    if name is not None:
        workspace.name = _normalize_name(name)
        workspace.save(update_fields=["name", "updated_at"])
        record_event(
            action=AuditAction.WORKSPACE_UPDATED,
            target_type="workspace",
            target_id=workspace.id,
            actor=actor,
            workspace=workspace,
            metadata={"name": workspace.name},
            request_id=request_id,
        )
    return workspace


@transaction.atomic
def add_workspace_member(
    *,
    workspace: Workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    email: str,
    role: str,
    request_id: str | None = None,
) -> WorkspaceMembership:
    """Add an already-existing, active user to the workspace by exact email.

    Deliberately does not support inviting non-existent accounts or a global
    user-search — only an exact normalized email for an existing account.
    """
    if role not in {
        WorkspaceRole.ADMIN,
        WorkspaceRole.SUPPORT_MANAGER,
        WorkspaceRole.SUPPORT_AGENT,
        WorkspaceRole.VIEWER,
    }:
        raise ValidationError({"role": "Invalid role."})

    if not can_manage_target_role(actor_role=actor_membership.role, target_role=role):
        raise PermissionDenied("You do not have permission to assign this role.")

    normalized_email = User.objects.normalize_email(email.strip())
    target_user = User.objects.filter(email__iexact=normalized_email, is_active=True).first()
    if target_user is None:
        # Deliberately generic: do not reveal whether the account exists.
        raise ValidationError({"email": "This account could not be added to the workspace."})

    existing = WorkspaceMembership.objects.filter(workspace=workspace, user=target_user).first()
    if existing is not None:
        if existing.is_active:
            raise ConflictError("This user is already a member of the workspace.")
        # Reactivate rather than create an uncontrolled duplicate row.
        existing.role = role
        existing.is_active = True
        existing.save(update_fields=["role", "is_active", "updated_at"])
        membership = existing
    else:
        try:
            membership = WorkspaceMembership.objects.create(
                workspace=workspace, user=target_user, role=role, is_active=True
            )
        except IntegrityError as exc:
            raise ConflictError("This user is already a member of the workspace.") from exc

    record_event(
        action=AuditAction.WORKSPACE_MEMBER_ADDED,
        target_type="workspace_membership",
        target_id=membership.id,
        actor=actor,
        workspace=workspace,
        metadata={"user_id": str(target_user.id), "role": role},
        request_id=request_id,
    )
    return membership


@transaction.atomic
def change_workspace_member_role(
    *,
    workspace: Workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    target_membership: WorkspaceMembership,
    new_role: str,
    request_id: str | None = None,
) -> WorkspaceMembership:
    """Generic role change. Can never create or modify an owner — ownership
    transfer is a dedicated service (see ``transfer_workspace_ownership``)."""
    if target_membership.workspace_id != workspace.id:
        raise ValidationError({"membership": "Membership does not belong to this workspace."})
    if new_role == WorkspaceRole.OWNER:
        raise ValidationError({"role": "Ownership can only change via ownership transfer."})
    if target_membership.role == WorkspaceRole.OWNER:
        raise ValidationError({"role": "The owner's role cannot be changed here."})
    if not can_manage_target_role(actor_role=actor_membership.role, target_role=new_role):
        raise PermissionDenied("You do not have permission to assign this role.")
    if not can_manage_target_role(
        actor_role=actor_membership.role, target_role=target_membership.role
    ):
        raise PermissionDenied("You do not have permission to manage this member.")

    old_role = target_membership.role
    target_membership.role = new_role
    target_membership.save(update_fields=["role", "updated_at"])

    record_event(
        action=AuditAction.WORKSPACE_MEMBER_ROLE_CHANGED,
        target_type="workspace_membership",
        target_id=target_membership.id,
        actor=actor,
        workspace=workspace,
        metadata={"old_role": old_role, "new_role": new_role},
        request_id=request_id,
    )
    return target_membership


@transaction.atomic
def remove_workspace_member(
    *,
    workspace: Workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    target_membership: WorkspaceMembership,
    request_id: str | None = None,
) -> None:
    """Deactivate a membership. History is preserved (``is_active=False``)
    rather than hard-deleted, which also gives ``add_workspace_member`` a
    clean reactivation path if the user rejoins."""
    if target_membership.workspace_id != workspace.id:
        raise ValidationError({"membership": "Membership does not belong to this workspace."})
    if target_membership.role == WorkspaceRole.OWNER:
        raise ValidationError({"membership": "The workspace owner cannot be removed."})
    if not can_manage_target_role(
        actor_role=actor_membership.role, target_role=target_membership.role
    ):
        raise PermissionDenied("You do not have permission to remove this member.")

    target_membership.is_active = False
    target_membership.save(update_fields=["is_active", "updated_at"])

    record_event(
        action=AuditAction.WORKSPACE_MEMBER_REMOVED,
        target_type="workspace_membership",
        target_id=target_membership.id,
        actor=actor,
        workspace=workspace,
        metadata={"user_id": str(target_membership.user_id), "role": target_membership.role},
        request_id=request_id,
    )


@transaction.atomic
def transfer_workspace_ownership(
    *,
    workspace: Workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    new_owner_membership: WorkspaceMembership,
    request_id: str | None = None,
) -> WorkspaceMembership:
    """Atomically promote ``new_owner_membership`` to owner and demote the
    current owner to admin. Row-locked so no transaction can observe (or
    commit) a moment with two owners or zero owners."""
    if actor_membership.role != WorkspaceRole.OWNER:
        raise PermissionDenied("Only the workspace owner may transfer ownership.")
    if new_owner_membership.workspace_id != workspace.id:
        raise ValidationError({"membership": "Target must be a member of this workspace."})
    if not new_owner_membership.is_active:
        raise ValidationError({"membership": "Target member is not active."})
    if new_owner_membership.user_id == actor_membership.user_id:
        raise ValidationError({"membership": "Cannot transfer ownership to yourself."})

    # Lock both rows (ordered by primary key to avoid deadlocks between
    # concurrent transfer attempts) before mutating either.
    locked_ids = sorted([str(actor_membership.id), str(new_owner_membership.id)])
    locked = {
        str(m.id): m
        for m in WorkspaceMembership.objects.select_for_update().filter(id__in=locked_ids)
    }
    current_owner = locked[str(actor_membership.id)]
    new_owner = locked[str(new_owner_membership.id)]

    if current_owner.role != WorkspaceRole.OWNER:
        # Stale request: ownership already changed since the caller loaded it.
        raise ConflictError("Ownership has already changed.")
    if not new_owner.is_active:
        raise ValidationError({"membership": "Target member is not active."})

    previous_owner_user_id = current_owner.user_id
    current_owner.role = WorkspaceRole.ADMIN
    current_owner.save(update_fields=["role", "updated_at"])
    new_owner.role = WorkspaceRole.OWNER
    new_owner.save(update_fields=["role", "updated_at"])

    record_event(
        action=AuditAction.WORKSPACE_OWNERSHIP_TRANSFERRED,
        target_type="workspace",
        target_id=workspace.id,
        actor=actor,
        workspace=workspace,
        metadata={
            "previous_owner_user_id": str(previous_owner_user_id),
            "new_owner_user_id": str(new_owner.user_id),
        },
        request_id=request_id,
    )
    return new_owner
