"""Web-chat ingress services (Phase 13 section 16-18, 41, 45).

Web chat is the one channel that never goes through the signed-adapter path
(``channel_ingress.adapters``) — its security model is the bounded, opaque
session capability defined here, not an HMAC signature (section 45). It
still terminates at the exact same canonical boundary as every other
channel: ``submit_chat_message`` builds a ``CanonicalInboundMessage`` and
hands it to the same ``ingest_channel_event``/async-processing pipeline
signed adapters use.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from conversations.models import Message
from conversations.selectors import message_list_for_conversation

from .errors import EndpointDisabledError, SessionInvalidError
from .models import (
    ChannelEndpoint,
    ChannelType,
    ChatSession,
    _generate_session_token,
    hash_session_token,
)
from .schemas import CanonicalInboundMessage
from .security import compute_payload_digest, enforce_body_size
from .services import ingest_channel_event


def bootstrap_chat_session(*, endpoint: ChannelEndpoint) -> tuple[ChatSession, str]:
    """Create a new anonymous session. Returns ``(session, plaintext_token)``
    — the plaintext token is returned exactly once, here, and never stored
    or logged (section 17)."""
    if endpoint.channel != ChannelType.WEB_CHAT or not endpoint.enabled:
        raise EndpointDisabledError()

    token = _generate_session_token()
    now = timezone.now()
    session = ChatSession.objects.create(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        token_hash=hash_session_token(token),
        expires_at=now + timedelta(seconds=settings.CHANNELS_CHAT_SESSION_TTL_SECONDS),
        last_seen_at=now,
    )
    return session, token


def get_session_for_token(*, token: str) -> ChatSession | None:
    """Constant-time-safe lookup: the token is hashed first (a plain
    equality query on the hash), so no per-row comparison of caller-supplied
    material is needed — the hash itself *is* the indexed lookup key
    (section 17)."""
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = ChatSession.objects.filter(token_hash=token_hash).select_related("endpoint").first()
    if session is None:
        return None
    if session.expires_at <= timezone.now():
        return None
    return session


def _session_event_id(*, session: ChatSession, client_message_id: str) -> str:
    """Namespaced by session (section 11): two different sessions on the
    same endpoint reusing the same client-generated id must never collide
    on one dedupe/idempotency slot."""
    return f"{session.id}:{client_message_id}"[:255]


@transaction.atomic
def submit_chat_message(*, session: ChatSession, client_message_id: str, body: str):
    """Idempotent client-message submission (section 11, 16-18).

    ``client_message_id`` is the caller's own stable idempotency identifier
    (section 11) — two submissions with the same id and the same body are
    one logical event (idempotent accept); the same id with a *different*
    body is ``idempotency_conflict`` (section 12), exactly like every other
    channel."""
    endpoint = session.endpoint
    if not endpoint.enabled:
        raise EndpointDisabledError()

    raw_body = body.encode("utf-8")
    enforce_body_size(raw_body)

    canonical = CanonicalInboundMessage(
        channel=ChannelType.WEB_CHAT,
        provider="web_chat",
        provider_event_id=_session_event_id(session=session, client_message_id=client_message_id),
        provider_thread_id=str(session.id),
        external_identity=str(session.id),
        subject="",
        body=body,
        received_at=timezone.now(),
    )
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id=canonical.provider_event_id,
        payload_digest=compute_payload_digest(raw_body),
        external_identity=canonical.external_identity,
        body=canonical.body,
        subject=canonical.subject,
        provider_thread_id=canonical.provider_thread_id,
    )
    session.last_seen_at = timezone.now()
    session.save(update_fields=["last_seen_at", "updated_at"])
    return event


def list_chat_messages(*, session: ChatSession, after: str | None = None) -> list[Message]:
    """Bounded, session-scoped retrieval of the conversation's messages
    (section 41) — never any other session's conversation, regardless of
    workspace/endpoint. ``after`` is an opaque message id cursor: only
    messages created strictly after it are returned.

    Always capped at ``CHANNEL_WEBCHAT_MESSAGE_HISTORY_LIMIT`` (Phase 14,
    Section 3): a widget re-opening a very old session polls the rest with
    further ``after``-cursor calls rather than pulling an unbounded
    transcript in one response.
    """
    conversation = session.conversation
    if conversation is None:
        return []
    queryset = message_list_for_conversation(conversation=conversation)
    if after:
        anchor = queryset.filter(pk=after).first()
        if anchor is not None:
            # Tie-broken on id, matching the queryset's own (created_at, id)
            # ordering, so two messages sharing a timestamp are never
            # skipped or duplicated across successive polls.
            queryset = queryset.filter(
                Q(created_at__gt=anchor.created_at)
                | Q(created_at=anchor.created_at, id__gt=anchor.id)
            )
    limit = settings.CHANNEL_WEBCHAT_MESSAGE_HISTORY_LIMIT
    return list(queryset[:limit])


def require_session(*, token: str) -> ChatSession:
    session = get_session_for_token(token=token)
    if session is None:
        raise SessionInvalidError()
    return session
