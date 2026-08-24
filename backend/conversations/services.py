"""Conversation and message domain services.

Views resolve tenant-scoped objects via selectors, check permissions, and
delegate every state transition here. Status transitions, assignment, and
message creation are implemented as explicit domain operations rather than
unrestricted field mutation.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from customers.models import Customer
from workspaces.models import WorkspaceMembership, WorkspaceRole

from .models import Conversation, ConversationStatus, Message, MessageDirection, MessageSenderType

#: Roles that may assign/reassign a conversation to any member of the
#: workspace. Other roles may only self-assign an unassigned conversation
#: (see ``assign_conversation``).
CONVERSATION_REASSIGN_ROLES = frozenset(
    {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.SUPPORT_MANAGER}
)

#: Legal conversation status transitions.
CONVERSATION_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    ConversationStatus.OPEN: frozenset({ConversationStatus.PENDING, ConversationStatus.CLOSED}),
    ConversationStatus.PENDING: frozenset({ConversationStatus.OPEN, ConversationStatus.CLOSED}),
    ConversationStatus.CLOSED: frozenset({ConversationStatus.OPEN}),
}


def _ensure_conversation_mutation_allowed(
    *, conversation: Conversation, actor_membership: WorkspaceMembership
) -> None:
    """Manager+ may mutate any conversation. A support agent may mutate only
    a conversation currently assigned to them."""
    if actor_membership.role in CONVERSATION_REASSIGN_ROLES:
        return
    if (
        actor_membership.role == WorkspaceRole.SUPPORT_AGENT
        and conversation.assigned_to_id == actor_membership.id
    ):
        return
    raise PermissionDenied("You do not have permission to modify this conversation.")


@transaction.atomic
def create_conversation(
    *,
    workspace,
    customer: Customer,
    channel: str,
    subject: str = "",
    external_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Conversation:
    if customer.workspace_id != workspace.id:
        raise ValidationError({"customer": "Customer does not belong to this workspace."})
    return Conversation.objects.create(
        workspace=workspace,
        customer=customer,
        channel=channel,
        subject=subject,
        external_id=external_id,
        metadata=metadata or {},
    )


@transaction.atomic
def assign_conversation(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    conversation: Conversation,
    target_membership: WorkspaceMembership,
    request_id: str | None = None,
) -> Conversation:
    """Assign/reassign a conversation. Managers may target anyone in the
    workspace; a support agent may only self-assign an unassigned
    conversation (self-assignment, never arbitrary reassignment to peers)."""
    if target_membership.workspace_id != workspace.id:
        raise ValidationError({"membership": "Assignee must belong to this workspace."})

    is_self_assign = target_membership.id == actor_membership.id
    if actor_membership.role not in CONVERSATION_REASSIGN_ROLES:
        if not is_self_assign:
            raise PermissionDenied("You may only assign a conversation to yourself.")
        if (
            conversation.assigned_to_id is not None
            and conversation.assigned_to_id != actor_membership.id
        ):
            raise PermissionDenied(
                "This conversation is already assigned; only a manager may reassign it."
            )

    was_assigned = conversation.assigned_to_id is not None
    conversation.assigned_to = target_membership
    conversation.save(update_fields=["assigned_to", "updated_at"])

    record_event(
        action=(
            AuditAction.CONVERSATION_REASSIGNED
            if was_assigned
            else AuditAction.CONVERSATION_ASSIGNED
        ),
        target_type="conversation",
        target_id=conversation.id,
        actor=actor,
        workspace=workspace,
        metadata={"assigned_to_membership_id": str(target_membership.id)},
        request_id=request_id,
    )
    return conversation


def self_assign_conversation(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    conversation: Conversation,
    request_id: str | None = None,
) -> Conversation:
    return assign_conversation(
        workspace=workspace,
        actor=actor,
        actor_membership=actor_membership,
        conversation=conversation,
        target_membership=actor_membership,
        request_id=request_id,
    )


@transaction.atomic
def change_conversation_status(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    conversation: Conversation,
    new_status: str,
    request_id: str | None = None,
) -> Conversation:
    _ensure_conversation_mutation_allowed(
        conversation=conversation, actor_membership=actor_membership
    )
    allowed = CONVERSATION_STATUS_TRANSITIONS.get(conversation.status, frozenset())
    if new_status not in allowed:
        raise ValidationError(
            {"status": f"Cannot transition from {conversation.status} to {new_status}."}
        )

    old_status = conversation.status
    conversation.status = new_status
    if new_status == ConversationStatus.CLOSED:
        conversation.closed_at = timezone.now()
    elif old_status == ConversationStatus.CLOSED:
        conversation.closed_at = None
    conversation.save(update_fields=["status", "closed_at", "updated_at"])

    action = (
        AuditAction.CONVERSATION_CLOSED
        if new_status == ConversationStatus.CLOSED
        else AuditAction.CONVERSATION_REOPENED if old_status == ConversationStatus.CLOSED else None
    )
    if action is not None:
        record_event(
            action=action,
            target_type="conversation",
            target_id=conversation.id,
            actor=actor,
            workspace=workspace,
            metadata={"old_status": old_status, "new_status": new_status},
            request_id=request_id,
        )
    return conversation


def close_conversation(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    conversation: Conversation,
    request_id: str | None = None,
) -> Conversation:
    return change_conversation_status(
        workspace=workspace,
        actor=actor,
        actor_membership=actor_membership,
        conversation=conversation,
        new_status=ConversationStatus.CLOSED,
        request_id=request_id,
    )


def reopen_conversation(
    *,
    workspace,
    actor: User,
    actor_membership: WorkspaceMembership,
    conversation: Conversation,
    request_id: str | None = None,
) -> Conversation:
    return change_conversation_status(
        workspace=workspace,
        actor=actor,
        actor_membership=actor_membership,
        conversation=conversation,
        new_status=ConversationStatus.OPEN,
        request_id=request_id,
    )


@transaction.atomic
def _create_message(
    *,
    workspace,
    conversation: Conversation,
    sender_type: str,
    direction: str,
    body: str,
    sender_membership: WorkspaceMembership | None = None,
    external_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message:
    if conversation.workspace_id != workspace.id:
        raise ValidationError({"conversation": "Conversation does not belong to this workspace."})
    if sender_membership is not None and sender_membership.workspace_id != workspace.id:
        raise ValidationError({"sender_membership": "Sender does not belong to this workspace."})

    message = Message.objects.create(
        workspace=workspace,
        conversation=conversation,
        sender_type=sender_type,
        sender_membership=sender_membership,
        direction=direction,
        body=body,
        external_id=external_id,
        metadata=metadata or {},
    )

    conversation.last_message_at = message.created_at
    update_fields = ["last_message_at", "updated_at"]
    if direction == MessageDirection.INBOUND and conversation.status == ConversationStatus.CLOSED:
        conversation.status = ConversationStatus.OPEN
        conversation.closed_at = None
        update_fields += ["status", "closed_at"]
    conversation.save(update_fields=update_fields)
    return message


def create_outbound_message(
    *,
    workspace,
    actor_membership: WorkspaceMembership,
    conversation: Conversation,
    body: str,
    external_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message:
    """SupportPilot -> customer. Sender identity is always the authenticated
    staff member's own membership — a client can never impersonate another
    sender through this API."""
    return _create_message(
        workspace=workspace,
        conversation=conversation,
        sender_type=MessageSenderType.HUMAN_AGENT,
        direction=MessageDirection.OUTBOUND,
        body=body,
        sender_membership=actor_membership,
        external_id=external_id,
        metadata=metadata,
    )


def create_internal_message(
    *,
    workspace,
    actor_membership: WorkspaceMembership,
    conversation: Conversation,
    body: str,
    external_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message:
    """Visible to support operations only, never to the customer."""
    return _create_message(
        workspace=workspace,
        conversation=conversation,
        sender_type=MessageSenderType.HUMAN_AGENT,
        direction=MessageDirection.INTERNAL,
        body=body,
        sender_membership=actor_membership,
        external_id=external_id,
        metadata=metadata,
    )


def create_ai_agent_message(
    *,
    workspace,
    conversation: Conversation,
    body: str,
    external_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message:
    """SupportPilot's agent orchestration -> customer (Phase 9, section 54).

    Distinct from ``create_outbound_message``: there is no authenticated
    staff ``actor_membership`` behind an agent-generated reply, so
    ``sender_membership`` is always null and the sender type is always
    ``ai_agent`` — never attributable to a human account."""
    return _create_message(
        workspace=workspace,
        conversation=conversation,
        sender_type=MessageSenderType.AI_AGENT,
        direction=MessageDirection.OUTBOUND,
        body=body,
        sender_membership=None,
        external_id=external_id,
        metadata=metadata,
    )


def create_inbound_message(
    *,
    workspace,
    conversation: Conversation,
    body: str,
    external_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Message:
    """Customer -> SupportPilot. Not exposed through the staff API in this
    phase — reserved for trusted future integration/webhook services. A
    closed conversation reopens automatically."""
    return _create_message(
        workspace=workspace,
        conversation=conversation,
        sender_type=MessageSenderType.CUSTOMER,
        direction=MessageDirection.INBOUND,
        body=body,
        sender_membership=None,
        external_id=external_id,
        metadata=metadata,
    )
