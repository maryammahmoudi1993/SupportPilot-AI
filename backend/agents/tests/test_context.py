"""Conversation context validation, filtering, normalization, and bounds."""

from __future__ import annotations

import pytest

from agents.context import (
    ConversationContextLimits,
    InvalidTriggerMessageError,
    build_conversation_context,
)
from conversations.models import MessageDirection, MessageSenderType
from conversations.tests.factories import ConversationFactory, MessageFactory


@pytest.mark.django_db
class TestConversationContext:
    def test_normalizes_roles_and_excludes_internal_and_system_messages(self):
        conversation = ConversationFactory()
        MessageFactory(conversation=conversation, body="first customer")
        MessageFactory(
            conversation=conversation,
            sender_type=MessageSenderType.HUMAN_AGENT,
            direction=MessageDirection.OUTBOUND,
            body="human answer",
        )
        MessageFactory(
            conversation=conversation,
            sender_type=MessageSenderType.HUMAN_AGENT,
            direction=MessageDirection.INTERNAL,
            body="private-secret-note",
        )
        MessageFactory(
            conversation=conversation,
            sender_type=MessageSenderType.SYSTEM,
            direction=MessageDirection.OUTBOUND,
            body="system metadata",
        )
        trigger = MessageFactory(conversation=conversation, body="current question")

        result = build_conversation_context(
            workspace=conversation.workspace,
            conversation=conversation,
            trigger_message=trigger,
        )

        assert [(message.role, message.content) for message in result.messages] == [
            ("user", "first customer"),
            ("assistant", "human answer"),
            ("user", "current question"),
        ]
        assert "private-secret-note" not in " ".join(item.content for item in result.messages)

    def test_newest_history_is_retained_trigger_is_unique_and_characters_are_bounded(self):
        conversation = ConversationFactory()
        oldest = MessageFactory(conversation=conversation, body="oldest-000")
        newest = MessageFactory(
            conversation=conversation,
            sender_type=MessageSenderType.AI_AGENT,
            direction=MessageDirection.OUTBOUND,
            body="recent-111",
        )
        trigger = MessageFactory(conversation=conversation, body="trigger-22")

        result = build_conversation_context(
            workspace=conversation.workspace,
            conversation=conversation,
            trigger_message=trigger,
            limits=ConversationContextLimits(max_messages=2, max_characters=15),
        )

        assert oldest.id not in [item.message_id for item in result.messages]
        assert [item.message_id for item in result.messages] == [newest.id, trigger.id]
        assert result.messages[0].content == "recen"
        assert result.character_count == 15
        assert result.truncated is True
        assert [item.message_id for item in result.messages].count(trigger.id) == 1

    def test_one_oversized_trigger_cannot_exceed_the_total_limit(self):
        conversation = ConversationFactory()
        trigger = MessageFactory(conversation=conversation, body="x" * 500)

        result = build_conversation_context(
            workspace=conversation.workspace,
            conversation=conversation,
            trigger_message=trigger,
            limits=ConversationContextLimits(max_messages=5, max_characters=40),
        )

        assert result.character_count == 40
        assert result.messages == (result.messages[0],)
        assert result.messages[0].truncated is True

    @pytest.mark.parametrize(
        ("sender_type", "direction"),
        [
            (MessageSenderType.AI_AGENT, MessageDirection.OUTBOUND),
            (MessageSenderType.HUMAN_AGENT, MessageDirection.INTERNAL),
            (MessageSenderType.CUSTOMER, MessageDirection.OUTBOUND),
        ],
    )
    def test_non_customer_inbound_trigger_is_rejected(self, sender_type, direction):
        conversation = ConversationFactory()
        trigger = MessageFactory(
            conversation=conversation,
            sender_type=sender_type,
            direction=direction,
        )

        with pytest.raises(InvalidTriggerMessageError):
            build_conversation_context(
                workspace=conversation.workspace,
                conversation=conversation,
                trigger_message=trigger,
            )

    def test_cross_conversation_and_cross_workspace_triggers_are_rejected(self):
        conversation = ConversationFactory()
        same_workspace_other = ConversationFactory(workspace=conversation.workspace)
        cross_conversation = MessageFactory(conversation=same_workspace_other)
        cross_workspace = MessageFactory()

        for trigger in (cross_conversation, cross_workspace):
            with pytest.raises(InvalidTriggerMessageError):
                build_conversation_context(
                    workspace=conversation.workspace,
                    conversation=conversation,
                    trigger_message=trigger,
                )
