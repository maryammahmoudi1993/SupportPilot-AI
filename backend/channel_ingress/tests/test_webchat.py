"""Web-chat session bootstrap, message submission, and isolation (Phase 13
section 16-18, 41, 58)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from channel_ingress.errors import (
    EndpointDisabledError,
    IdempotencyConflictError,
    SessionInvalidError,
)
from channel_ingress.models import ChannelEndpointStatus, ChatSession, InboundChannelEventStatus
from channel_ingress.tests.factories import ChatSessionFactory, WebChatEndpointFactory
from channel_ingress.webchat import (
    bootstrap_chat_session,
    get_session_for_token,
    list_chat_messages,
    require_session,
    submit_chat_message,
)

pytestmark = pytest.mark.django_db


def test_bootstrap_creates_a_session_and_returns_a_plaintext_token_once():
    endpoint = WebChatEndpointFactory()
    session, token = bootstrap_chat_session(endpoint=endpoint)
    assert len(token) >= 32
    assert session.token_hash != token
    assert ChatSession.objects.filter(pk=session.pk).exists()


def test_bootstrap_rejects_a_disabled_endpoint():
    endpoint = WebChatEndpointFactory(status=ChannelEndpointStatus.DISABLED)
    with pytest.raises(EndpointDisabledError):
        bootstrap_chat_session(endpoint=endpoint)


def test_valid_token_resolves_the_session():
    endpoint = WebChatEndpointFactory()
    session, token = bootstrap_chat_session(endpoint=endpoint)
    resolved = get_session_for_token(token=token)
    assert resolved is not None
    assert resolved.id == session.id


def test_unknown_token_resolves_to_none():
    assert get_session_for_token(token="not-a-real-token") is None


def test_expired_token_is_rejected():
    from channel_ingress.models import hash_session_token

    token = "a-token-whose-hash-we-store"
    ChatSessionFactory(
        token_hash=hash_session_token(token),
        expires_at=timezone.now() - timezone.timedelta(seconds=1),
    )
    assert get_session_for_token(token=token) is None
    with pytest.raises(SessionInvalidError):
        require_session(token=token)


def test_submit_message_creates_an_inbound_event():
    endpoint = WebChatEndpointFactory()
    session, _ = bootstrap_chat_session(endpoint=endpoint)
    event = submit_chat_message(session=session, client_message_id="msg-1", body="I need help")
    assert event.body == "I need help"
    assert event.status == InboundChannelEventStatus.RECEIVED


def test_duplicate_client_message_id_same_body_is_idempotent():
    endpoint = WebChatEndpointFactory()
    session, _ = bootstrap_chat_session(endpoint=endpoint)
    first = submit_chat_message(session=session, client_message_id="msg-1", body="hi")
    second = submit_chat_message(session=session, client_message_id="msg-1", body="hi")
    assert first.id == second.id


def test_duplicate_client_message_id_conflicting_body_is_rejected():
    endpoint = WebChatEndpointFactory()
    session, _ = bootstrap_chat_session(endpoint=endpoint)
    submit_chat_message(session=session, client_message_id="msg-1", body="hi")
    with pytest.raises(IdempotencyConflictError):
        submit_chat_message(
            session=session, client_message_id="msg-1", body="something else entirely"
        )


def test_same_client_message_id_on_two_sessions_does_not_collide():
    endpoint = WebChatEndpointFactory()
    session_a, _ = bootstrap_chat_session(endpoint=endpoint)
    session_b, _ = bootstrap_chat_session(endpoint=endpoint)
    event_a = submit_chat_message(session=session_a, client_message_id="msg-1", body="hi from a")
    event_b = submit_chat_message(session=session_b, client_message_id="msg-1", body="hi from b")
    assert event_a.id != event_b.id


def test_oversized_message_is_rejected(settings):
    settings.CHANNELS_MAX_INBOUND_BODY_BYTES = 10
    endpoint = WebChatEndpointFactory()
    session, _ = bootstrap_chat_session(endpoint=endpoint)
    from channel_ingress.errors import PayloadTooLargeError

    with pytest.raises(PayloadTooLargeError):
        submit_chat_message(
            session=session, client_message_id="msg-1", body="this body is too long"
        )


def test_empty_message_is_rejected_at_the_serializer_boundary():
    from channel_ingress.serializers import ChatMessageSubmitSerializer

    serializer = ChatMessageSubmitSerializer(data={"client_message_id": "msg-1", "body": ""})
    assert not serializer.is_valid()
    assert "body" in serializer.errors


def test_list_messages_before_any_processing_is_empty():
    endpoint = WebChatEndpointFactory()
    session, _ = bootstrap_chat_session(endpoint=endpoint)
    assert list_chat_messages(session=session) == []


def test_list_messages_is_scoped_to_the_sessions_own_conversation():
    """Section 41, 58: one session must never see another session's
    conversation, even on the same endpoint/workspace."""
    endpoint = WebChatEndpointFactory()
    session_a, _ = bootstrap_chat_session(endpoint=endpoint)
    session_b, _ = bootstrap_chat_session(endpoint=endpoint)

    from conversations.tests.factories import ConversationFactory
    from customers.tests.factories import CustomerFactory

    customer = CustomerFactory(workspace=endpoint.workspace)
    conversation = ConversationFactory(workspace=endpoint.workspace, customer=customer)
    session_a.conversation = conversation
    session_a.customer = customer
    session_a.save(update_fields=["conversation", "customer"])

    from conversations.services import create_ai_agent_message

    create_ai_agent_message(workspace=endpoint.workspace, conversation=conversation, body="hi")

    assert len(list_chat_messages(session=session_a)) == 1
    assert list_chat_messages(session=session_b) == []


def test_after_cursor_ties_are_broken_by_sequence_not_random_id():
    """Phase 16 Checkpoint 2 Part B (section 6) regression: the ``after``
    cursor used to tie-break a ``created_at`` collision on ``id`` (a random
    UUID) while ``message_list_for_conversation`` orders by
    ``(created_at, sequence)`` — a genuine mismatch that could skip or
    duplicate a message across polls whenever the anchor's UUID happened to
    sort the "wrong" way relative to its true (sequence) position. Forces
    the exact tie and proves both directions: nothing already seen is
    re-returned, and nothing is silently skipped."""
    from channel_ingress.tests.factories import ChatSessionFactory
    from conversations.models import Message
    from conversations.tests.factories import ConversationFactory, MessageFactory
    from customers.tests.factories import CustomerFactory

    endpoint = WebChatEndpointFactory()
    customer = CustomerFactory(workspace=endpoint.workspace)
    conversation = ConversationFactory(workspace=endpoint.workspace, customer=customer)
    session = ChatSessionFactory(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        customer=customer,
        conversation=conversation,
    )

    messages = [MessageFactory(conversation=conversation, body=f"msg-{i}") for i in range(4)]
    same_ts = timezone.now()
    # Force a genuine created_at tie across all four messages, the same way
    # a real DB timestamp collision would look — sequence is untouched
    # (still strictly increasing in creation order) since it is a DB
    # sequence, never an auto_now_add column.
    Message.objects.filter(id__in=[m.id for m in messages]).update(created_at=same_ts)
    ordered = list(Message.objects.filter(conversation=conversation).order_by("sequence"))

    # Poll from the very start.
    first_page = list_chat_messages(session=session)
    assert [m.id for m in first_page] == [m.id for m in ordered]

    # Poll again "after" the second message, purely by its id — the bug
    # this regression closes would use ``id__gt`` here and could exclude a
    # later-``sequence`` message whose UUID happens to sort lower, or
    # re-include an earlier one whose UUID happens to sort higher.
    anchor = ordered[1]
    next_page = list_chat_messages(session=session, after=str(anchor.id))
    assert [m.id for m in next_page] == [m.id for m in ordered[2:]]
