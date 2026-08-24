"""Tenant-scoped read selectors for conversations and messages."""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.http import Http404

from workspaces.models import Workspace

from .models import Conversation, Message


def conversation_list_for_workspace(
    *,
    workspace: Workspace,
    customer_id: UUID | str | None = None,
    status: str | None = None,
    channel: str | None = None,
    assigned_to: UUID | str | None = None,
    unassigned: bool | None = None,
) -> QuerySet[Conversation]:
    qs = Conversation.objects.filter(workspace=workspace).select_related(
        "customer", "assigned_to", "assigned_to__user"
    )
    if customer_id is not None:
        qs = qs.filter(customer_id=customer_id)
    if status is not None:
        qs = qs.filter(status=status)
    if channel is not None:
        qs = qs.filter(channel=channel)
    if unassigned:
        qs = qs.filter(assigned_to__isnull=True)
    elif assigned_to is not None:
        qs = qs.filter(
            assigned_to=assigned_to if isinstance(assigned_to, UUID) else UUID(assigned_to)
        )
    return qs.order_by("-last_message_at", "-created_at")


def conversation_get_for_workspace_or_404(
    *, workspace: Workspace, conversation_id: UUID | str
) -> Conversation:
    conversation = (
        Conversation.objects.filter(workspace=workspace, pk=conversation_id)
        .select_related("customer", "assigned_to", "assigned_to__user")
        .first()
    )
    if conversation is None:
        raise Http404("Conversation not found.")
    return conversation


def message_list_for_conversation(*, conversation: Conversation) -> QuerySet[Message]:
    return (
        Message.objects.filter(conversation=conversation)
        .select_related("sender_membership", "sender_membership__user")
        .order_by("created_at")
    )


def message_get_for_workspace_or_404(
    *, workspace: Workspace, conversation: Conversation, message_id: UUID | str
) -> Message:
    """Scoped by *both* workspace and conversation (Phase 9, section 102-103):
    a message belonging to a different conversation — even in the same
    workspace — 404s exactly as a cross-tenant message would, rather than
    being resolvable by ID alone."""
    message = Message.objects.filter(
        workspace=workspace, conversation=conversation, pk=message_id
    ).first()
    if message is None:
        raise Http404("Message not found.")
    return message
