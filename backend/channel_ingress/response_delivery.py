"""Response routing through the reused Phase 10 durable delivery engine
(Phase 13 section 39-42, 54).

``route_channel_response`` is called once, from ``agents.services`` (see its
``_schedule_channel_response_routing`` hook), the moment an ``AgentRun``
reaches a terminal state that produced a customer-visible output message.
It only ever *creates* durable rows — it never talks to a provider itself
(exactly mirroring ``notifications.notification_delivery
.create_or_reuse_notification_delivery``). ``handle_channel_response_delivery_attempt``
is the registered ``DeliveryChannel.CHANNEL_RESPONSE`` handler
(``channel_ingress.apps.ChannelIngressConfig.ready``); it runs later, once a
worker has claimed the ``Delivery``, and is the only place that calls the
existing Phase 7 email provider.

Critical invariant (section 54): agent execution and response delivery are
distinct persisted operations. A successful run followed by a *delivery*
failure only ever retries the durable ``Delivery`` — never re-runs the
agent. Nothing in this module can trigger a second ``AgentRun``.
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings

from integrations.errors import IntegrationError
from integrations.services import send_notification
from notifications.models import Delivery, DeliveryChannel
from notifications.services import (
    complete_delivery_failure,
    complete_delivery_success,
    create_delivery,
)
from observability.tracing import domain_span, finalize_domain_span

from .models import ChannelEndpoint, ChannelResponseDelivery, ChannelType

logger = logging.getLogger("supportpilot")

UNEXPECTED_ERROR_CODE = "channel_response_delivery_unexpected_error"
MISSING_SNAPSHOT_ERROR_CODE = "channel_response_delivery_missing"

#: Channels whose response actually needs an external durable delivery.
#: WEB_CHAT's authoritative response is the Conversation Message itself
#: (section 41) — nothing to route externally. GENERIC_WEBHOOK has no
#: concrete outbound delivery mechanism in this phase (documented as
#: inbound-only, see ``docs/architecture/multichannel-ingress.md``).
_EXTERNAL_DELIVERY_CHANNELS = frozenset({ChannelType.EMAIL})


def route_channel_response(*, run) -> ChannelResponseDelivery | None:
    """Route ``run``'s customer-visible output message back to its
    originating channel, if that channel needs an external delivery.
    Returns ``None`` for a channel that needs no routing (web chat, or a
    conversation with no channel origin at all — e.g. staff-created)."""
    conversation = run.conversation
    if conversation is None or run.output_message_id is None:
        return None

    endpoint_id = (conversation.metadata or {}).get("channel_endpoint_id")
    if not endpoint_id:
        return None

    endpoint = ChannelEndpoint.objects.filter(pk=endpoint_id, workspace=run.workspace).first()
    if endpoint is None or endpoint.channel not in _EXTERNAL_DELIVERY_CHANNELS:
        return None

    return _create_or_reuse_response_delivery(endpoint=endpoint, run=run, conversation=conversation)


def _create_or_reuse_response_delivery(
    *, endpoint: ChannelEndpoint, run, conversation
) -> ChannelResponseDelivery:
    message = run.output_message
    existing = ChannelResponseDelivery.objects.filter(source_message=message).first()
    if existing is not None:
        return existing

    destination = _destination_address(endpoint=endpoint, conversation=conversation)
    thread_reference = ""
    if conversation.external_id:
        thread_reference = conversation.external_id
    subject = conversation.subject or "Re: your message"

    delivery = create_delivery(workspace=run.workspace, channel=DeliveryChannel.CHANNEL_RESPONSE)
    return ChannelResponseDelivery.objects.create(
        delivery=delivery,
        source_message=message,
        endpoint=endpoint,
        destination_address=destination,
        subject=subject[:200],
        body=message.body,
        thread_reference=thread_reference,
        idempotency_key=f"channel_response:{message.id}",
    )


def _destination_address(*, endpoint: ChannelEndpoint, conversation) -> str:
    customer = conversation.customer
    if customer.email:
        return str(customer.email)
    # Section 42: the routing destination must come from normalized
    # authoritative channel state, never a customer-controlled metadata
    # field taken as a credential. A customer resolved through the EMAIL
    # adapter always has an email (it *is* their identity key), so this is
    # defensive-only.
    return str(endpoint.configuration.get("fallback_reply_address", ""))


def handle_channel_response_delivery_attempt(*, delivery: Delivery, claim_token: uuid.UUID) -> None:
    """The registered ``DeliveryChannel.CHANNEL_RESPONSE`` handler. Never
    bypasses the Phase 10 ownership-aware completion services — every exit
    path completes through ``complete_delivery_success``/
    ``complete_delivery_failure``, which re-verify ``claim_token`` before
    writing anything."""
    response_delivery = ChannelResponseDelivery.objects.filter(delivery=delivery).first()
    if response_delivery is None:
        complete_delivery_failure(
            delivery_id=delivery.id,
            claim_token=claim_token,
            safe_error_code=MISSING_SNAPSHOT_ERROR_CODE,
            retryable=False,
        )
        return

    with domain_span(
        "channel.response_route",
        attributes={
            "channel": str(response_delivery.endpoint.channel),
            "attempt.number": str(delivery.attempt_count),
        },
    ) as span:
        try:
            message = send_notification(
                workspace=delivery.workspace,
                remaining_seconds=float(settings.INTEGRATIONS_MAX_TIMEOUT_SECONDS),
                recipient_email=response_delivery.destination_address,
                subject=response_delivery.subject,
                body=response_delivery.body,
                idempotency_key=response_delivery.idempotency_key,
            )
        except IntegrationError as exc:
            finalize_domain_span(span, outcome="failed", is_error=True)
            complete_delivery_failure(
                delivery_id=delivery.id,
                claim_token=claim_token,
                safe_error_code=exc.code,
                retryable=exc.retryable,
            )
            return
        except Exception as exc:  # noqa: BLE001 - documented fail-closed boundary
            logger.error(
                "channel_response_delivery_unexpected_error",
                extra={
                    "event": "channel_response_delivery_unexpected_error",
                    "workspace_id": str(delivery.workspace_id),
                    "delivery_id": str(delivery.id),
                    "attempt_number": delivery.attempt_count,
                    "exception_type": type(exc).__name__,
                },
            )
            finalize_domain_span(span, outcome="failed", is_error=True)
            complete_delivery_failure(
                delivery_id=delivery.id,
                claim_token=claim_token,
                safe_error_code=UNEXPECTED_ERROR_CODE,
                retryable=False,
            )
            return

        if message.message_id:
            ChannelResponseDelivery.objects.filter(pk=response_delivery.pk).update(
                provider_message_id=message.message_id
            )
        finalize_domain_span(span, outcome="succeeded")
        complete_delivery_success(delivery_id=delivery.id, claim_token=claim_token)
