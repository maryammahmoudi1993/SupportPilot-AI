"""Conversation context validation, filtering, normalization, and bounds."""

from __future__ import annotations

import pytest
from django.utils import timezone

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

    def test_newest_history_is_retained_even_when_created_at_ties(self):
        """Phase 16 Part F (section 31/33) regression: this is the
        deterministic root cause behind the historically-observed flake in
        ``test_newest_history_is_retained_...`` above — two messages
        sharing the exact same ``created_at`` (a real, if rare,
        possibility) previously sorted by ``id``, a random UUID with zero
        correlation to creation order. Reproduced concretely before the
        fix: forcing a tie made the *older* message survive the trim while
        the newer one was dropped, inverting this test's own guarantee.
        ``Message.sequence`` (a DB-assigned, strictly-increasing tie-
        breaker) closes that gap; this test forces the exact tie condition
        that broke it, rather than hoping wall-clock timing collides on its
        own."""
        from conversations.models import Message

        conversation = ConversationFactory()
        oldest = MessageFactory(conversation=conversation, body="oldest-000")
        newest = MessageFactory(
            conversation=conversation,
            sender_type=MessageSenderType.AI_AGENT,
            direction=MessageDirection.OUTBOUND,
            body="recent-111",
        )
        trigger = MessageFactory(conversation=conversation, body="trigger-22")

        # Force an exact created_at collision across all three messages —
        # the condition under which a random-UUID tie-break previously
        # produced the wrong (non-chronological) ordering.
        same_instant = timezone.now()
        Message.objects.filter(pk__in=[oldest.pk, newest.pk, trigger.pk]).update(
            created_at=same_instant
        )
        trigger.refresh_from_db()

        result = build_conversation_context(
            workspace=conversation.workspace,
            conversation=conversation,
            trigger_message=trigger,
            limits=ConversationContextLimits(max_messages=2, max_characters=100),
        )

        # sequence (insertion order), not the timestamp, is what must still
        # correctly identify "newest" once created_at can no longer do so.
        assert oldest.id not in [item.message_id for item in result.messages]
        assert [item.message_id for item in result.messages] == [newest.id, trigger.id]

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
