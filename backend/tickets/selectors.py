"""Tenant-scoped read selectors for tickets."""

from __future__ import annotations

from uuid import UUID

from django.db.models import Case, IntegerField, QuerySet, When
from django.http import Http404

from workspaces.models import Workspace

from .models import Ticket, TicketPriority

#: Urgent/high priority sort first, independent of alphabetic enum order.
_PRIORITY_ORDER = Case(
    When(priority=TicketPriority.URGENT, then=0),
    When(priority=TicketPriority.HIGH, then=1),
    When(priority=TicketPriority.NORMAL, then=2),
    When(priority=TicketPriority.LOW, then=3),
    output_field=IntegerField(),
)


def ticket_list_for_workspace(
    *,
    workspace: Workspace,
    status: str | None = None,
    priority: str | None = None,
    customer_id: UUID | str | None = None,
    assigned_to: UUID | str | None = None,
    unassigned: bool | None = None,
    conversation_id: UUID | str | None = None,
) -> QuerySet[Ticket]:
    qs = Ticket.objects.filter(workspace=workspace).select_related(
        "customer", "assigned_to", "assigned_to__user", "conversation"
    )
    if status is not None:
        qs = qs.filter(status=status)
    if priority is not None:
        qs = qs.filter(priority=priority)
    if customer_id is not None:
        qs = qs.filter(customer_id=customer_id)
    if conversation_id is not None:
        qs = qs.filter(conversation_id=conversation_id)
    if unassigned:
        qs = qs.filter(assigned_to__isnull=True)
    elif assigned_to is not None:
        qs = qs.filter(
            assigned_to=assigned_to if isinstance(assigned_to, UUID) else UUID(assigned_to)
        )
    return qs.annotate(_priority_order=_PRIORITY_ORDER).order_by("_priority_order", "-created_at")


def ticket_get_for_workspace_or_404(*, workspace: Workspace, ticket_id: UUID | str) -> Ticket:
    ticket = (
        Ticket.objects.filter(workspace=workspace, pk=ticket_id)
        .select_related("customer", "assigned_to", "assigned_to__user", "conversation")
        .first()
    )
    if ticket is None:
        raise Http404("Ticket not found.")
    return ticket


def ticket_get_by_id_for_workspace(*, workspace: Workspace, ticket_id: str) -> Ticket | None:
    """Like ``ticket_get_for_workspace_or_404`` but returns ``None`` instead
    of raising — used by ``integrations.tools`` ticket handlers, which
    normalize "not found" into their own stable tool error code."""
    if not ticket_id:
        return None
    try:
        UUID(str(ticket_id))
    except (ValueError, AttributeError):
        return None
    return (
        Ticket.objects.filter(workspace=workspace, pk=ticket_id)
        .select_related("customer", "assigned_to", "assigned_to__user", "conversation")
        .first()
    )
