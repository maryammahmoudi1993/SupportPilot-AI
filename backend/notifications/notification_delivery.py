"""Notification-specific delivery producer + channel handler (Phase 10
Block 2).

Converts ``notification.send`` from a direct/synchronous provider call into
durable enqueue semantics: ``create_or_reuse_notification_delivery`` is
called from the tool handler (``integrations.tools``) and only ever creates
the durable rows — it never talks to a provider. ``handle_notification_delivery_attempt``
is the registered ``DeliveryChannel.NOTIFICATION`` handler
(``notifications.apps.NotificationsConfig.ready``); it runs later, once a
worker has claimed the ``Delivery``, and is the only place that calls the
existing Phase 7 ``NotificationProvider`` (section 13-14).
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings

from integrations.errors import IntegrationError
from integrations.services import send_notification
from workspaces.models import Workspace

from .models import Delivery, DeliveryChannel, NotificationDelivery, NotificationMedium
from .services import complete_delivery_failure, complete_delivery_success, create_delivery

logger = logging.getLogger("supportpilot")

#: A truly unexpected (non-``IntegrationError``) failure fails closed —
#: terminal, never retried (section 15). An unclassified failure might be a
#: permanent bug rather than a transient outage; silently retrying an
#: unknown failure until the attempt budget burns out is worse than
#: surfacing it as DEAD immediately for an operator to investigate.
#:
#: Deliberately *not* logged via ``logger.exception``/``exc_info=True``
#: (unlike ``tools/execution.py``'s handler-boundary convention): the
#: exception here can originate from an external provider/library this
#: block does not control, so it is untrusted and may carry secret- or
#: credential-like text. Only stable, safe metadata (event, workspace/
#: delivery id, attempt number, exception *type* name) is ever logged —
#: never ``str(exc)``, ``repr(exc)``, ``exc.args``, or a rendered traceback
#: — and nothing beyond the stable error code below is ever persisted to a
#: delivery field.
UNEXPECTED_ERROR_CODE = "notification_delivery_unexpected_error"
MISSING_SNAPSHOT_ERROR_CODE = "notification_delivery_missing"


def create_or_reuse_notification_delivery(
    *, tool_execution, workspace: Workspace, recipient_email: str, subject: str, body: str
) -> NotificationDelivery:
    """One ``NotificationDelivery`` per source ``ToolExecution`` (section
    11) — the ``OneToOneField`` makes a second call for the same execution
    (a replayed/reset ``notification.send`` attempt) return the existing row
    rather than creating a second logical notification.

    The recipient/subject/body snapshot is frozen here, at creation time
    (section 7) — every later delivery attempt (including retries) sends
    exactly this snapshot, never a value re-read from the current, possibly
    since-mutated ``Customer`` record.
    """
    existing = NotificationDelivery.objects.filter(source_tool_execution=tool_execution).first()
    if existing is not None:
        return existing

    delivery = create_delivery(workspace=workspace, channel=DeliveryChannel.NOTIFICATION)
    return NotificationDelivery.objects.create(
        delivery=delivery,
        source_tool_execution=tool_execution,
        medium=NotificationMedium.EMAIL,
        recipient_email=recipient_email,
        subject=subject,
        body=body,
        # Stable across every attempt this delivery ever makes (section 12)
        # — reusing the exact key the pre-Block-2 synchronous handler used,
        # so a provider capable of server-side dedup (the deterministic
        # fake included) sees the same identity on every retry.
        idempotency_key=f"notification.send:{tool_execution.id}",
    )


def handle_notification_delivery_attempt(*, delivery: Delivery, claim_token: uuid.UUID) -> None:
    """The registered ``DeliveryChannel.NOTIFICATION`` handler (section 14).
    Never bypasses Block 1's ownership-aware completion services — every
    exit path below completes through ``complete_delivery_success`` /
    ``complete_delivery_failure``, which re-verify ``claim_token`` before
    writing anything."""
    notification_delivery = NotificationDelivery.objects.filter(delivery=delivery).first()
    if notification_delivery is None:
        # Defensive: a Delivery with channel=NOTIFICATION but no snapshot
        # row is a data-integrity gap, never a transient provider condition
        # — terminal, not retried.
        complete_delivery_failure(
            delivery_id=delivery.id,
            claim_token=claim_token,
            safe_error_code=MISSING_SNAPSHOT_ERROR_CODE,
            retryable=False,
        )
        return

    try:
        # The Phase 6 tool-execution deadline that originally bounded
        # ``notification.send`` no longer applies here — this call runs
        # from an independent, later worker attempt, so it gets its own
        # full server-owned timeout budget (section 74-75 of the Phase 7
        # conventions still apply: the provider-level timeout is bounded by
        # the same settings, just not by a specific tool call's remaining
        # time).
        message = send_notification(
            workspace=delivery.workspace,
            remaining_seconds=float(settings.INTEGRATIONS_MAX_TIMEOUT_SECONDS),
            recipient_email=notification_delivery.recipient_email,
            subject=notification_delivery.subject,
            body=notification_delivery.body,
            idempotency_key=notification_delivery.idempotency_key,
        )
    except IntegrationError as exc:
        # Reuses the existing Phase 7 normalized error taxonomy directly
        # (section 13, 15) rather than inventing a second classifier:
        # ``exc.code`` is always a safe, stable string and ``exc.retryable``
        # already encodes exactly the timeout/rate-limit/unavailable ->
        # retryable, auth/config/invalid-request -> terminal policy this
        # block calls for. Only ``.code`` is ever persisted — never
        # ``.safe_message`` or ``str(exc)`` — so a value that happened to be
        # passed into an error's message can never reach a stored field.
        complete_delivery_failure(
            delivery_id=delivery.id,
            claim_token=claim_token,
            safe_error_code=exc.code,
            retryable=exc.retryable,
        )
        return
    except Exception as exc:  # noqa: BLE001 - the documented fail-closed boundary above
        # Section 27, 34 (Block 2 remediation): this exception is untrusted
        # — it may originate from a provider/library we do not control and
        # could carry credential- or secret-like text in its message or
        # args. Never ``logger.exception``/``exc_info=True`` here: with
        # ``DEBUG`` on, the plain "verbose" formatter renders a full
        # traceback (including ``str(exc)``) into the log line, and no
        # formatter is trusted to redact it. Only stable, safe metadata is
        # ever logged — never ``str(exc)``, ``repr(exc)``, ``exc.args``, or
        # a traceback.
        logger.error(
            "notification_delivery_unexpected_error",
            extra={
                "event": "notification_delivery_unexpected_error",
                "workspace_id": str(delivery.workspace_id),
                "delivery_id": str(delivery.id),
                "attempt_number": delivery.attempt_count,
                "exception_type": type(exc).__name__,
            },
        )
        complete_delivery_failure(
            delivery_id=delivery.id,
            claim_token=claim_token,
            safe_error_code=UNEXPECTED_ERROR_CODE,
            retryable=False,
        )
        return

    if message.message_id:
        NotificationDelivery.objects.filter(pk=notification_delivery.pk).update(
            provider_message_id=message.message_id
        )
    complete_delivery_success(delivery_id=delivery.id, claim_token=claim_token)
