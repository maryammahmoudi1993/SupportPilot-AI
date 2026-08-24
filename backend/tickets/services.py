"""Ticket domain services.

Views resolve tenant-scoped objects via selectors, check permissions, and
delegate every state transition here.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from conversations.models import Conversation
from customers.models import Customer
from workspaces.models import WorkspaceMembership, WorkspaceRole

from .models import (
    HUMAN_HANDOFF_ACTIVE_STATUSES,
    HumanHandoff,
    HumanHandoffStatus,
    Ticket,
    TicketStatus,
)

#: Roles that may assign/reassign a ticket to any member of the workspace.
#: Other roles may only self-assign an unassigned ticket.
TICKET_REASSIGN_ROLES = frozenset(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER}
)

#: Legal ticket status transitions.
TICKET_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    TicketStatus.OPEN: frozenset(
        {TicketStatus.IN_PROGRESS, TicketStatus.PENDING, TicketStatus.RESOLVED, TicketStatus.CLOSED}
    ),
    TicketStatus.IN_PROGRESS: frozenset(
        {TicketStatus.OPEN, TicketStatus.PENDING, TicketStatus.RESOLVED, TicketStatus.CLOSED}
    ),
    TicketStatus.PENDING: frozenset(
        {TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED}
    ),
    TicketStatus.RESOLVED: frozenset(
        {TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.CLOSED}
    ),
    TicketStatus.CLOSED: frozenset({TicketStatus.OPEN}),
}

WRITABLE_TICKET_FIELDS = frozenset({"subject", "description", "priority", "due_at", "metadata"})


def _ensure_ticket_mutation_allowed(
    *, ticket: Ticket, actor_membership: WorkspaceMembership
) -> None:
    """Manager+ may mutate any ticket. A support agent may mutate only a
    ticket currently assigned to them."""
    if actor_membership.role in TICKET_REASSIGN_ROLES:
        return
    if (
        actor_membership.role == WorkspaceRole.SUPPORT_AGENT
        and ticket.assigned_to_id == actor_membership.id
    ):
        return
    raise PermissionDenied("You do not have permission to modify this ticket.")


@transaction.atomic
def create_ticket(
    *,
    workspace,
    customer: Customer,
    subject: str,
    description: str = "",
    priority: str | None = None,
    conversation: Conversation | None = None,
    due_at=None,
    metadata: dict[str, Any] | None = None,
) -> Ticket:
    if customer.workspace_id != workspace.id:
        raise ValidationError({"customer": "Customer does not belong to this workspace."})
    if conversation is not None and conversation.workspace_id != workspace.id:
        raise ValidationError({"conversation": "Conversation does not belong to this workspace."})

    fields: dict[str, Any] = {
        "subject": subject,
        "description": description,
        "due_at": due_at,
        "metadata": metadata or {},
    }
    if priority is not None:
        fields["priority"] = priority

    return Ticket.objects.create(
        workspace=workspace,
        customer=customer,
        conversation=conversation,
        **fields,
    )


@transaction.atomic
def update_ticket(
    *,
    workspace,
    ticket: Ticket,
    actor_membership: WorkspaceMembership,
    data: dict[str, Any],
) -> Ticket:
    _ensure_ticket_mutation_allowed(ticket=ticket, actor_membership=actor_membership)
    for field in WRITABLE_TICKET_FIELDS:
        if field in data:
            setattr(ticket, field, data[field])
    ticket.save()
    return ticket


@transaction.atomic
def assign_ticket(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    ticket: Ticket,
    target_membership: WorkspaceMembership,
    request_id: str | None = None,
) -> Ticket:
    """Assign/reassign a ticket. Managers may target anyone in the
    workspace; a support agent may only self-assign an unassigned ticket."""
    if target_membership.workspace_id != workspace.id:
        raise ValidationError({"membership": "Assignee must belong to this workspace."})

    is_self_assign = target_membership.id == actor_membership.id
    if actor_membership.role not in TICKET_REASSIGN_ROLES:
        if not is_self_assign:
            raise PermissionDenied("You may only assign a ticket to yourself.")
        if ticket.assigned_to_id is not None and ticket.assigned_to_id != actor_membership.id:
            raise PermissionDenied(
                "This ticket is already assigned; only a manager may reassign it."
            )

    was_assigned = ticket.assigned_to_id is not None
    ticket.assigned_to = target_membership
    ticket.save(update_fields=["assigned_to", "updated_at"])

    record_event(
        action=AuditAction.TICKET_REASSIGNED if was_assigned else AuditAction.TICKET_ASSIGNED,
        target_type="ticket",
        target_id=ticket.id,
        actor=actor,
        workspace=workspace,
        metadata={"assigned_to_membership_id": str(target_membership.id)},
        request_id=request_id,
    )
    return ticket


def self_assign_ticket(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    ticket: Ticket,
    request_id: str | None = None,
) -> Ticket:
    return assign_ticket(
        workspace=workspace,
        actor=actor,
        actor_membership=actor_membership,
        ticket=ticket,
        target_membership=actor_membership,
        request_id=request_id,
    )


@transaction.atomic
def unassign_ticket(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    ticket: Ticket,
    request_id: str | None = None,
) -> Ticket:
    if actor_membership.role not in TICKET_REASSIGN_ROLES:
        raise PermissionDenied("You do not have permission to unassign this ticket.")

    ticket.assigned_to = None
    ticket.save(update_fields=["assigned_to", "updated_at"])
    record_event(
        action=AuditAction.TICKET_REASSIGNED,
        target_type="ticket",
        target_id=ticket.id,
        actor=actor,
        workspace=workspace,
        metadata={"assigned_to_membership_id": None},
        request_id=request_id,
    )
    return ticket


@transaction.atomic
def change_ticket_status(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    ticket: Ticket,
    new_status: str,
    request_id: str | None = None,
) -> Ticket:
    _ensure_ticket_mutation_allowed(ticket=ticket, actor_membership=actor_membership)
    allowed = TICKET_STATUS_TRANSITIONS.get(ticket.status, frozenset())
    if new_status not in allowed:
        raise ValidationError(
            {"status": f"Cannot transition from {ticket.status} to {new_status}."}
        )

    old_status = ticket.status
    ticket.status = new_status
    if new_status == TicketStatus.RESOLVED:
        ticket.resolved_at = timezone.now()
    elif old_status == TicketStatus.RESOLVED:
        ticket.resolved_at = None
    ticket.save(update_fields=["status", "resolved_at", "updated_at"])

    if new_status == TicketStatus.RESOLVED:
        action = AuditAction.TICKET_RESOLVED
    elif old_status == TicketStatus.RESOLVED and new_status == TicketStatus.OPEN:
        action = AuditAction.TICKET_REOPENED
    else:
        action = AuditAction.TICKET_STATUS_CHANGED
    record_event(
        action=action,
        target_type="ticket",
        target_id=ticket.id,
        actor=actor,
        workspace=workspace,
        metadata={"old_status": old_status, "new_status": new_status},
        request_id=request_id,
    )
    return ticket


def resolve_ticket(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    ticket: Ticket,
    request_id: str | None = None,
) -> Ticket:
    return change_ticket_status(
        workspace=workspace,
        actor=actor,
        actor_membership=actor_membership,
        ticket=ticket,
        new_status=TicketStatus.RESOLVED,
        request_id=request_id,
    )


#: Fields an agent-triggered ``ticket.update`` tool may set directly (a
#: strict subset of ``WRITABLE_TICKET_FIELDS`` — no ``due_at``/``metadata``
#: free-form mutation from a model-proposed action).
AGENT_WRITABLE_TICKET_FIELDS = frozenset({"priority"})


@transaction.atomic
def apply_agent_ticket_update(
    *,
    workspace,
    ticket: Ticket,
    actor: User | None,
    priority: str | None = None,
    status: str | None = None,
    note: str | None = None,
) -> Ticket:
    """Apply a bounded ticket mutation on behalf of an agent run.

    Distinct from ``update_ticket``/``change_ticket_status`` (which require a
    human ``actor_membership`` to enforce agent/manager-vs-self-assignment
    rules): an agent-triggered mutation's authorization boundary is the
    Phase 6 ``ToolBinding`` on the agent version, not a workspace membership,
    so this path never requires or fabricates one. It still reuses the same
    domain constants (``TICKET_STATUS_TRANSITIONS``,
    ``AGENT_WRITABLE_TICKET_FIELDS``) so behavior never diverges from the
    human-driven paths: reuse the existing ticket service rather than
    duplicating ticket business logic in a second, tool-specific copy.
    """
    if priority is not None:
        ticket.priority = priority
    if note:
        # Append-only, bounded note — never overwrites prior description.
        separator = "\n\n" if ticket.description else ""
        ticket.description = f"{ticket.description}{separator}{note}"[:20000]
    if status is not None and status != ticket.status:
        allowed = TICKET_STATUS_TRANSITIONS.get(ticket.status, frozenset())
        if status not in allowed:
            raise ValidationError(
                {"status": f"Cannot transition from {ticket.status} to {status}."}
            )
        old_status = ticket.status
        ticket.status = status
        if status == TicketStatus.RESOLVED:
            ticket.resolved_at = timezone.now()
        elif old_status == TicketStatus.RESOLVED:
            ticket.resolved_at = None
        ticket.save()
        action = (
            AuditAction.TICKET_RESOLVED
            if status == TicketStatus.RESOLVED
            else (
                AuditAction.TICKET_REOPENED
                if old_status == TicketStatus.RESOLVED and status == TicketStatus.OPEN
                else AuditAction.TICKET_STATUS_CHANGED
            )
        )
        record_event(
            action=action,
            target_type="ticket",
            target_id=ticket.id,
            actor=actor,
            workspace=workspace,
            metadata={"old_status": old_status, "new_status": status, "via": "agent_tool"},
        )
    else:
        ticket.save()
    return ticket


def reopen_ticket(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    ticket: Ticket,
    request_id: str | None = None,
) -> Ticket:
    return change_ticket_status(
        workspace=workspace,
        actor=actor,
        actor_membership=actor_membership,
        ticket=ticket,
        new_status=TicketStatus.OPEN,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Human handoff (Phase 9, section 44-53)
# ---------------------------------------------------------------------------

#: Roles that may assign/resolve/cancel a handoff — mirrors the ticket
#: reassignment roles; a plain support agent may still view the queue
#: (read-only) but does not manage it directly.
HANDOFF_MANAGE_ROLES = frozenset(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER}
)


@transaction.atomic
def create_or_reuse_handoff(
    *,
    workspace,
    conversation: Conversation,
    reason_code: str,
    safe_summary: str,
    agent_run=None,
    ticket: Ticket | None = None,
    request_id: str | None = None,
) -> tuple[HumanHandoff, bool]:
    """Create a pending handoff for this conversation, or return the
    conversation's existing *active* handoff unchanged (section 51: one
    AgentRun must not spawn ten identical pending handoffs; a retried
    handoff trigger for the same still-open conversation is a no-op, not a
    duplicate). Returns ``(handoff, created)``.

    Race-safe: the model's partial unique constraint
    (``handoff_one_active_per_conversation``) is the actual invariant — a
    concurrent double-create loses the database race and falls back to
    re-reading the now-existing row, rather than ever creating two.
    """
    if conversation.workspace_id != workspace.id:
        raise ValidationError({"conversation": "Conversation does not belong to this workspace."})
    if agent_run is not None and agent_run.workspace_id != workspace.id:
        raise ValidationError({"agent_run": "Agent run does not belong to this workspace."})
    if ticket is not None and ticket.workspace_id != workspace.id:
        raise ValidationError({"ticket": "Ticket does not belong to this workspace."})

    existing = (
        HumanHandoff.objects.select_for_update()
        .filter(conversation=conversation, status__in=HUMAN_HANDOFF_ACTIVE_STATUSES)
        .first()
    )
    if existing is not None:
        return existing, False

    try:
        with transaction.atomic():
            handoff = HumanHandoff.objects.create(
                workspace=workspace,
                conversation=conversation,
                agent_run=agent_run,
                ticket=ticket,
                reason_code=reason_code,
                safe_summary=safe_summary,
            )
    except IntegrityError:
        # Lost a concurrent race for this conversation's active-handoff slot.
        handoff = HumanHandoff.objects.get(
            conversation=conversation, status__in=HUMAN_HANDOFF_ACTIVE_STATUSES
        )
        return handoff, False

    record_event(
        action=AuditAction.HUMAN_HANDOFF_CREATED,
        target_type="human_handoff",
        target_id=handoff.id,
        actor=None,
        workspace=workspace,
        metadata={"conversation_id": str(conversation.id), "reason_code": reason_code},
        request_id=request_id,
    )
    return handoff, True


@transaction.atomic
def assign_handoff(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    handoff: HumanHandoff,
    target_membership: WorkspaceMembership | None = None,
    request_id: str | None = None,
) -> HumanHandoff:
    if actor_membership.role not in HANDOFF_MANAGE_ROLES:
        raise PermissionDenied("You do not have permission to assign handoffs.")
    target = target_membership or actor_membership
    if target.workspace_id != workspace.id:
        raise ValidationError({"membership": "Assignee must belong to this workspace."})

    locked = HumanHandoff.objects.select_for_update().get(pk=handoff.pk)
    if locked.status not in HUMAN_HANDOFF_ACTIVE_STATUSES:
        raise ValidationError({"status": "Only an active handoff can be assigned."})
    locked.assigned_to = target
    locked.status = HumanHandoffStatus.ASSIGNED
    locked.save(update_fields=["assigned_to", "status", "updated_at"])

    record_event(
        action=AuditAction.HUMAN_HANDOFF_ASSIGNED,
        target_type="human_handoff",
        target_id=locked.id,
        actor=actor,
        workspace=workspace,
        metadata={"assigned_to_membership_id": str(target.id)},
        request_id=request_id,
    )
    return locked


@transaction.atomic
def resolve_handoff(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    handoff: HumanHandoff,
    request_id: str | None = None,
) -> HumanHandoff:
    if actor_membership.role not in HANDOFF_MANAGE_ROLES:
        raise PermissionDenied("You do not have permission to resolve handoffs.")

    locked = HumanHandoff.objects.select_for_update().get(pk=handoff.pk)
    if locked.status not in HUMAN_HANDOFF_ACTIVE_STATUSES:
        raise ValidationError({"status": "Only an active handoff can be resolved."})
    locked.status = HumanHandoffStatus.RESOLVED
    locked.resolved_at = timezone.now()
    locked.save(update_fields=["status", "resolved_at", "updated_at"])

    record_event(
        action=AuditAction.HUMAN_HANDOFF_RESOLVED,
        target_type="human_handoff",
        target_id=locked.id,
        actor=actor,
        workspace=workspace,
        metadata={},
        request_id=request_id,
    )
    return locked


def cancel_handoffs_for_run(*, agent_run, reason: str = "run_cancelled") -> None:
    """Cancel any still-active handoff created by a now-cancelled run
    (mirrors ``approvals.services.cancel_approval_for_execution``). Never
    raises on "nothing to cancel" — most runs never create a handoff."""
    with transaction.atomic():
        for handoff in HumanHandoff.objects.select_for_update().filter(
            agent_run=agent_run, status__in=HUMAN_HANDOFF_ACTIVE_STATUSES
        ):
            handoff.status = HumanHandoffStatus.CANCELLED
            handoff.save(update_fields=["status", "updated_at"])
            record_event(
                action=AuditAction.HUMAN_HANDOFF_CANCELLED,
                target_type="human_handoff",
                target_id=handoff.id,
                actor=None,
                workspace=handoff.workspace,
                metadata={"reason": reason},
            )
