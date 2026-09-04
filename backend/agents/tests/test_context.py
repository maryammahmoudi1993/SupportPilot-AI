"""Conversation context validation, filtering, normalization, and bounds."""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
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


class TestConversationContextQueryBounds:
    """Phase 16 Checkpoint 2 Part G (section 22): a conversation's total
    message count must never drive the query count or the size of the
    in-memory candidate set — only ``max_messages`` should. Growth-bound,
    not a fragile exact count, per the checkpoint's own guidance."""

    def _captured_queries(self, *, conversation, trigger, limits=None):
        with CaptureQueriesContext(connection) as ctx:
            build_conversation_context(
                workspace=conversation.workspace,
                conversation=conversation,
                trigger_message=trigger,
                limits=limits,
            )
        return ctx.captured_queries

    @pytest.mark.django_db
    def test_query_count_does_not_grow_with_conversation_length(self):
        # Query *count* alone doesn't prove boundedness — a single
        # unbounded SELECT iterated in Python is still exactly one query
        # regardless of row count. What must not grow is query count
        # *and* (proven below) the row-fetching query must carry a LIMIT
        # that never depends on how long the conversation actually is.
        conversation = ConversationFactory()
        limits = ConversationContextLimits(max_messages=5, max_characters=10_000)

        MessageFactory.create_batch(20, conversation=conversation)
        small_trigger = MessageFactory(conversation=conversation)
        small_queries = self._captured_queries(
            conversation=conversation, trigger=small_trigger, limits=limits
        )

        MessageFactory.create_batch(300, conversation=conversation)
        large_trigger = MessageFactory(conversation=conversation)
        large_queries = self._captured_queries(
            conversation=conversation, trigger=large_trigger, limits=limits
        )

        assert len(small_queries) == len(large_queries)

    @pytest.mark.django_db
    def test_the_row_fetching_query_is_db_bounded_by_max_messages(self):
        """Section 22's actual requirement: the row-fetch itself must carry
        a ``LIMIT`` tied to ``max_messages``, never "load all rows then
        slice in Python" — a query that happens to run once is not
        evidence of boundedness if it has no LIMIT clause."""
        conversation = ConversationFactory()
        limits = ConversationContextLimits(max_messages=5, max_characters=10_000)
        MessageFactory.create_batch(300, conversation=conversation)
        trigger = MessageFactory(conversation=conversation)

        queries = self._captured_queries(conversation=conversation, trigger=trigger, limits=limits)

        limited = [
            q for q in queries if "conversations_message" in q["sql"] and "LIMIT" in q["sql"]
        ]
        assert limited, "expected a LIMIT-bounded fetch of the conversation's messages"
        assert any(f"LIMIT {limits.max_messages}" in q["sql"] for q in limited)

    @pytest.mark.django_db
    def test_only_the_newest_max_messages_are_ever_fetched_from_a_long_history(self):
        """Correctness companion to the query-count bound above: a long
        history must still retain exactly the newest eligible messages, not
        an arbitrary subset of whatever the (now-bounded) query happened to
        fetch."""
        conversation = ConversationFactory()
        limits = ConversationContextLimits(max_messages=5, max_characters=10_000)

        for i in range(50):
            MessageFactory(
                conversation=conversation,
                sender_type=MessageSenderType.AI_AGENT,
                direction=MessageDirection.OUTBOUND,
                body=f"assistant-{i}",
            )
        trigger = MessageFactory(
            conversation=conversation,
            sender_type=MessageSenderType.CUSTOMER,
            direction=MessageDirection.INBOUND,
            body="current question",
        )

        context = build_conversation_context(
            workspace=conversation.workspace,
            conversation=conversation,
            trigger_message=trigger,
            limits=limits,
        )

        bodies = [m.content for m in context.messages]
        assert bodies == [
            "assistant-46",
            "assistant-47",
            "assistant-48",
            "assistant-49",
            "current question",
        ]
        assert context.truncated is True
        assert context.available_message_count == 51
