"""Ingress domain services (Phase 13 section 9-13, 31-38).

``ingest_channel_event`` is the durable dedupe boundary: it persists exactly
one ``InboundChannelEvent`` per logical provider event and commits before
anything else happens (section 34). ``process_inbound_channel_event`` is the
thin async-processing body a Celery task (and the recovery sweeper) both
call — it claims the event, resolves identity/conversation, persists the
customer message through the established ``conversations`` service, and
hands off to the *existing* support-agent orchestration
(``agents.orchestration.start_support_agent_run`` — section 32). Nothing in
this module talks to an LLM provider, a tool, or a policy directly; that
seam is Phase 9's, reused unchanged.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from agents.errors import AgentError
from agents.orchestration import start_support_agent_run
from conversations.services import create_inbound_message

from .conversation_resolution import resolve_conversation
from .errors import IdempotencyConflictError, OrchestrationFailedError
from .identity import resolve_customer_identity
from .models import (
    ChannelEndpoint,
    ChannelType,
    ChatSession,
    InboundChannelEvent,
    InboundChannelEventStatus,
)

logger = logging.getLogger("supportpilot")


def _dispatch_event(event_id) -> None:
    from .tasks import process_inbound_channel_event_task

    process_inbound_channel_event_task.delay(str(event_id))


@transaction.atomic
def ingest_channel_event(
    *,
    endpoint: ChannelEndpoint,
    provider_event_id: str,
    payload_digest: str,
    external_identity: str,
    body: str,
    subject: str = "",
    provider_thread_id: str | None = None,
    provider_message_id: str | None = None,
) -> InboundChannelEvent:
    """Idempotently create the one durable row for this logical event
    (section 11).

    Mirrors ``agents.services.create_agent_run``'s trigger-message
    idempotency pattern exactly: a ``select_for_update`` existence check
    guards the common case, an ``IntegrityError`` catch on the ``create()``
    resolves the race a concurrent duplicate delivery can still hit between
    that check and this transaction's commit. A duplicate with an identical
    payload digest returns the existing row unchanged (idempotent accept,
    section 11); a duplicate with a *different* digest is a distinct
    logical event colliding on the same provider event id, which is a
    caller/provider bug, not something to silently paper over (section 12).
    """
    existing = (
        InboundChannelEvent.objects.select_for_update()
        .filter(endpoint=endpoint, provider_event_id=provider_event_id)
        .first()
    )
    if existing is not None:
        if existing.payload_digest != payload_digest:
            raise IdempotencyConflictError()
        _observe_ingress_duplicate(endpoint)
        return existing

    try:
        with transaction.atomic():
            event = InboundChannelEvent.objects.create(
                workspace=endpoint.workspace,
                endpoint=endpoint,
                provider_event_id=provider_event_id,
                payload_digest=payload_digest,
                provider_thread_id=provider_thread_id or "",
                provider_message_id=provider_message_id or "",
                external_identity=external_identity,
                subject=subject,
                body=body,
            )
    except IntegrityError:
        existing = InboundChannelEvent.objects.get(
            endpoint=endpoint, provider_event_id=provider_event_id
        )
        if existing.payload_digest != payload_digest:
            raise IdempotencyConflictError() from None
        _observe_ingress_duplicate(endpoint)
        return existing

    transaction.on_commit(lambda: _dispatch_event(event.id))
    _observe_ingress_created(endpoint)
    return event


def _observe_ingress_created(endpoint: ChannelEndpoint) -> None:
    def _record() -> None:
        from observability.metrics import observe_channel_ingress_received

        try:
            observe_channel_ingress_received(channel=endpoint.channel)
        except Exception:  # noqa: BLE001 - telemetry must fail open
            logger.warning(
                "channel_ingress_metrics_recording_failed",
                extra={"event": "metrics_error", "endpoint_id": str(endpoint.id)},
            )

    transaction.on_commit(_record)


def _observe_ingress_duplicate(endpoint: ChannelEndpoint) -> None:
    # Deliberately observed immediately, not via ``on_commit``: this branch
    # never writes anything new — there is no rollback to protect against
    # (section 11's dedupe path is read-then-return, not a fresh commit).
    from observability.metrics import observe_channel_ingress_duplicate

    try:
        observe_channel_ingress_duplicate(channel=endpoint.channel)
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning(
            "channel_ingress_metrics_recording_failed",
            extra={"event": "metrics_error", "endpoint_id": str(endpoint.id)},
        )


def claim_inbound_channel_event(event_id) -> InboundChannelEvent | None:
    """Atomically transition ``received -> processing`` (section 10, 37-38).
    Returns ``None`` if another worker already claimed (or completed) it —
    the same idempotent-start guard shape as ``agents.services.claim_agent_run``,
    so duplicate Celery delivery of the same event id is always safe."""
    with transaction.atomic():
        event = InboundChannelEvent.objects.select_for_update().get(pk=event_id)
        if event.status != InboundChannelEventStatus.RECEIVED:
            return None
        event.status = InboundChannelEventStatus.PROCESSING
        event.processing_started_at = timezone.now()
        event.save(update_fields=["status", "processing_started_at", "updated_at"])
    return event


def mark_event_processed(*, event: InboundChannelEvent, conversation, message) -> None:
    InboundChannelEvent.objects.filter(pk=event.pk).update(
        status=InboundChannelEventStatus.PROCESSED,
        conversation=conversation,
        message=message,
        processed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def mark_event_failed(*, event: InboundChannelEvent, code: str) -> None:
    InboundChannelEvent.objects.filter(pk=event.pk).update(
        status=InboundChannelEventStatus.FAILED,
        failure_code=code[:64],
        processed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def process_inbound_channel_event(event_id) -> str:
    """Claim, then run identity/conversation/message resolution and hand off
    to the existing support-agent orchestration (section 32-33, 38).

    Safe to call more than once for the same ``event_id``: a second call
    after the first already reached ``PROCESSED``/``FAILED`` finds nothing
    claimable and returns immediately (section 38) — no duplicate customer
    Message, no duplicate ``AgentRun`` (``create_inbound_message`` has no
    dedupe of its own, but ``start_support_agent_run`` reuses the same
    ``AgentRun.trigger_message`` ``OneToOneField`` invariant regardless, so
    even a hypothetical double-processed event could never start a second
    run for the same message).
    """
    event = claim_inbound_channel_event(event_id)
    if event is None:
        return InboundChannelEvent.objects.get(pk=event_id).status

    endpoint = event.endpoint
    canonical = _canonical_from_event(event)
    started = timezone.now()

    from observability.tracing import domain_span, finalize_domain_span

    with domain_span("channel.ingress", attributes={"channel": str(endpoint.channel)}) as span:
        try:
            with transaction.atomic():
                customer = resolve_customer_identity(
                    workspace=endpoint.workspace, endpoint=endpoint, canonical=canonical
                )
                conversation = _resolve_conversation_with_retry(
                    workspace=endpoint.workspace,
                    endpoint=endpoint,
                    customer=customer,
                    canonical=canonical,
                )
                _link_chat_session(
                    endpoint=endpoint,
                    canonical=canonical,
                    conversation=conversation,
                    customer=customer,
                )
                message = create_inbound_message(
                    workspace=endpoint.workspace,
                    conversation=conversation,
                    body=canonical.body,
                    external_id=canonical.provider_message_id,
                    metadata={"inbound_channel_event_id": str(event.id)},
                )
                mark_event_processed(event=event, conversation=conversation, message=message)
                run = start_support_agent_run(
                    workspace=endpoint.workspace,
                    actor=None,
                    conversation=conversation,
                    trigger_message=message,
                    agent_version=endpoint.agent_version,
                )
        except AgentError:
            logger.warning(
                "channel_ingress_orchestration_failed",
                extra={
                    "event": "channel_ingress_orchestration_failed",
                    "inbound_event_id": str(event.id),
                },
            )
            mark_event_failed(event=event, code=OrchestrationFailedError.code)
            finalize_domain_span(span, outcome="failed", is_error=True)
            _observe_ingress_terminal(endpoint=endpoint, outcome="failed", started=started)
            return InboundChannelEventStatus.FAILED
        except Exception:  # noqa: BLE001 - fail-taxonomy boundary, see errors.py
            logger.exception(
                "channel_ingress_processing_failed",
                extra={
                    "event": "channel_ingress_processing_failed",
                    "inbound_event_id": str(event.id),
                },
            )
            mark_event_failed(event=event, code="processing_failed")
            finalize_domain_span(span, outcome="failed", is_error=True)
            _observe_ingress_terminal(endpoint=endpoint, outcome="failed", started=started)
            return InboundChannelEventStatus.FAILED

        del run  # dispatch already scheduled by create_agent_run's on_commit hook
        finalize_domain_span(span, outcome="succeeded")

    _observe_ingress_terminal(endpoint=endpoint, outcome="processed", started=started)
    return InboundChannelEventStatus.PROCESSED


def _observe_ingress_terminal(*, endpoint: ChannelEndpoint, outcome: str, started) -> None:
    from observability.metrics import observe_channel_ingress_terminal

    try:
        observe_channel_ingress_terminal(
            channel=endpoint.channel,
            outcome=outcome,
            duration_seconds=(timezone.now() - started).total_seconds(),
        )
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning(
            "channel_ingress_metrics_recording_failed",
            extra={"event": "metrics_error", "endpoint_id": str(endpoint.id)},
        )


def _canonical_from_event(event: InboundChannelEvent):
    """Reconstructs the already-normalized canonical message from the
    fields ``ingest_channel_event`` persisted (section 34) — the raw
    provider payload itself was never persisted at all (only its digest,
    section 8), so this worker boundary works entirely from the bounded,
    normalized fields the HTTP-facing adapter already validated."""
    from .schemas import CanonicalInboundMessage

    return CanonicalInboundMessage(
        channel=event.endpoint.channel,
        provider=event.endpoint.channel,
        provider_event_id=event.provider_event_id,
        provider_thread_id=event.provider_thread_id or None,
        provider_message_id=event.provider_message_id or None,
        external_identity=event.external_identity,
        subject=event.subject,
        body=event.body,
        received_at=event.received_at,
    )


def _link_chat_session(*, endpoint, canonical, conversation, customer) -> None:
    """Section 41: a web-chat session's ``conversation``/``customer`` are
    resolved once, on its first message, and cached on the ``ChatSession``
    row so ``channel_ingress.webchat.list_chat_messages`` never has to
    re-derive them. Idempotent — a later message for the same session finds
    ``conversation__isnull=False`` already and this is a no-op."""
    if endpoint.channel != ChannelType.WEB_CHAT or not canonical.provider_thread_id:
        return
    ChatSession.objects.filter(pk=canonical.provider_thread_id, conversation__isnull=True).update(
        conversation=conversation, customer=customer
    )


def _resolve_conversation_with_retry(*, workspace, endpoint, customer, canonical):
    """A rare race (two distinct inbound events on the same new thread
    processed concurrently) can lose to ``Conversation``'s
    ``uniq_conversation_workspace_external_id`` constraint; on that specific
    conflict, the loser simply re-reads the winner's row rather than
    failing the whole event (section 61)."""
    try:
        return resolve_conversation(
            workspace=workspace, endpoint=endpoint, customer=customer, canonical=canonical
        )
    except IntegrityError:
        from conversations.models import Conversation

        from .conversation_resolution import thread_external_id

        if not canonical.provider_thread_id:
            raise
        external_id = thread_external_id(
            endpoint=endpoint, provider_thread_id=canonical.provider_thread_id
        )
        return Conversation.objects.get(workspace=workspace, external_id=external_id)
