"""Tenant-scoped, bounded conversation context for support-agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.db.models import Q

from conversations.models import (
    Conversation,
    Message,
    MessageDirection,
    MessageSenderType,
)
from conversations.selectors import message_list_for_conversation
from workspaces.models import Workspace

from .errors import AgentError

ContextRole = Literal["user", "assistant"]


class InvalidTriggerMessageError(AgentError):
    code = "invalid_trigger_message"
    safe_message = "The trigger message is not a valid customer message for this conversation."


@dataclass(frozen=True)
class ConversationContextLimits:
    max_messages: int
    max_characters: int

    @classmethod
    def from_settings(cls) -> ConversationContextLimits:
        return cls(
            max_messages=settings.AGENTS_CONTEXT_MAX_MESSAGES,
            max_characters=settings.AGENTS_CONTEXT_MAX_CHARACTERS,
        )


@dataclass(frozen=True)
class ContextMessage:
    message_id: UUID
    role: ContextRole
    content: str
    created_at: datetime
    truncated: bool = False


@dataclass(frozen=True)
class ConversationContext:
    conversation_id: UUID
    trigger_message_id: UUID
    messages: tuple[ContextMessage, ...]
    truncated: bool
    available_message_count: int

    @property
    def character_count(self) -> int:
        return sum(len(message.content) for message in self.messages)


def validate_trigger_message(
    *, workspace: Workspace, conversation: Conversation, trigger_message: Message
) -> None:
    """Validate the server-owned customer turn before any retrieval/model call."""
    if (
        conversation.workspace_id != workspace.id
        or trigger_message.workspace_id != workspace.id
        or trigger_message.conversation_id != conversation.id
        or trigger_message.sender_type != MessageSenderType.CUSTOMER
        or trigger_message.direction != MessageDirection.INBOUND
        or not trigger_message.body.strip()
    ):
        raise InvalidTriggerMessageError()


def _normalized_role(message: Message) -> ContextRole | None:
    if (
        message.sender_type == MessageSenderType.CUSTOMER
        and message.direction == MessageDirection.INBOUND
    ):
        return "user"
    if message.sender_type in {MessageSenderType.HUMAN_AGENT, MessageSenderType.AI_AGENT} and (
        message.direction == MessageDirection.OUTBOUND
    ):
        return "assistant"
    return None


# Phase 16 Checkpoint 2 Part G (section 22): the same eligibility rule as
# _normalized_role, expressed as a DB filter so a conversation with a very
# long history never requires loading every one of its messages into Python
# just to find the newest ``max_messages`` eligible ones (see
# ``build_conversation_context``'s bounded query below).
_ELIGIBLE_ROLE_FILTER = Q(
    sender_type=MessageSenderType.CUSTOMER, direction=MessageDirection.INBOUND
) | Q(
    sender_type__in=(MessageSenderType.HUMAN_AGENT, MessageSenderType.AI_AGENT),
    direction=MessageDirection.OUTBOUND,
)


def _bounded_message(message: Message, *, role: ContextRole, limit: int) -> ContextMessage:
    content = message.body[:limit]
    return ContextMessage(
        message_id=message.id,
        role=role,
        content=content,
        created_at=message.created_at,
        truncated=len(content) < len(message.body),
    )


def build_conversation_context(
    *,
    workspace: Workspace,
    conversation: Conversation,
    trigger_message: Message,
    limits: ConversationContextLimits | None = None,
) -> ConversationContext:
    """Return newest safe history plus exactly one authoritative trigger.

    Character counting is the sum of normalized message content lengths.
    The trigger consumes the budget first and is truncated at the right edge
    when necessary. Remaining messages are considered newest-first, then
    returned chronologically; oldest messages are therefore dropped first.
    Internal/system/unknown message variants are never normalized blindly.
    """
    validate_trigger_message(
        workspace=workspace, conversation=conversation, trigger_message=trigger_message
    )
    selected_limits = limits or ConversationContextLimits.from_settings()
    if selected_limits.max_messages < 1 or selected_limits.max_characters < 1:
        raise ValueError("Conversation context limits must be positive.")

    eligible_qs = (
        message_list_for_conversation(conversation=conversation)
        .filter(workspace=workspace, created_at__lte=trigger_message.created_at)
        .filter(_ELIGIBLE_ROLE_FILTER)
    )
    # Phase 16 Checkpoint 2 Part G (section 22): bounded at the DB layer —
    # only the newest ``max_messages`` eligible rows are ever fetched into
    # Python, regardless of how long the conversation's full history is.
    # ``available_count`` still reflects the true total (a single indexed
    # COUNT query, not a row fetch) so ``truncated`` below is exact even
    # though the candidate list itself is capped.
    available_count = eligible_qs.count()
    newest_candidates = list(
        eligible_qs.order_by("-created_at", "-sequence")[: selected_limits.max_messages]
    )

    trigger_context = _bounded_message(
        trigger_message, role="user", limit=selected_limits.max_characters
    )
    remaining_characters = selected_limits.max_characters - len(trigger_context.content)
    retained_newest_first: list[ContextMessage] = []
    for message in newest_candidates:
        if message.id == trigger_message.id:
            continue
        if len(retained_newest_first) >= selected_limits.max_messages - 1:
            break
        if remaining_characters <= 0:
            break
        role = _normalized_role(message)
        assert role is not None  # guaranteed by _ELIGIBLE_ROLE_FILTER above
        normalized = _bounded_message(message, role=role, limit=remaining_characters)
        if not normalized.content:
            continue
        retained_newest_first.append(normalized)
        remaining_characters -= len(normalized.content)

    retained = tuple(reversed(retained_newest_first)) + (trigger_context,)
    content_was_truncated = any(message.truncated for message in retained)
    return ConversationContext(
        conversation_id=conversation.id,
        trigger_message_id=trigger_message.id,
        messages=retained,
        truncated=content_was_truncated or len(retained) < available_count,
        available_message_count=available_count,
    )
