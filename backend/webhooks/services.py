"""Webhook endpoint management, event production/fanout, and the WEBHOOK
channel handler (Phase 10 Block 3).

Every write path below follows the same shape already established in
``approvals/services.py`` / ``integrations/services.py``: a transaction
around the persistence + audit event, server-derived operational fields
only, and normalized safe errors — no second architecture.
"""

from __future__ import annotations

import logging
import uuid
from functools import partial

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditAction
from audit.services import record_event
from integrations.crypto import CredentialEncryptionError, decrypt_credentials, encrypt_credentials
from notifications.models import Delivery, DeliveryChannel, DeliveryStatus
from notifications.services import (
    complete_delivery_failure,
    complete_delivery_success,
    create_delivery,
    dispatch_delivery_for_processing,
)

from . import selectors
from .classification import classify_http_status
from .errors import (
    WebhookDeliveryNotRedrivableError,
    WebhookEndpointDisabledError,
    WebhookError,
    WebhookInvalidEventTypeError,
    WebhookSigningNotConfiguredError,
)
from .models import WebhookDelivery, WebhookEndpoint, WebhookEndpointStatus, WebhookEvent
from .security import parse_webhook_url, resolve_and_validate
from .signing import build_signed_request, generate_signing_secret
from .transport import send_pinned_request

logger = logging.getLogger("supportpilot")

UNEXPECTED_ERROR_CODE = "webhook_delivery_unexpected_error"
MISSING_WEBHOOK_DELIVERY_ERROR_CODE = "webhook_delivery_missing"

MAX_NAME_LENGTH = 200


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_event_types(event_types) -> None:
    if not isinstance(event_types, list) or not event_types:
        raise WebhookInvalidEventTypeError()
    if len(set(event_types)) != len(event_types):
        raise WebhookInvalidEventTypeError()
    valid = set(selectors.valid_event_types())
    if not set(event_types) <= valid:
        raise WebhookInvalidEventTypeError()


def _best_effort_ssrf_check(url: str) -> None:
    """Immediate creation/update-time feedback only (a bad URL fails fast
    rather than silently queuing deliveries doomed to fail) — never the
    actual security boundary. ``handle_webhook_delivery_attempt`` always
    re-validates independently at send time (section 23), since DNS can
    legitimately change between now and then."""
    parsed = parse_webhook_url(url)
    resolve_and_validate(parsed.hostname, parsed.port)


# ---------------------------------------------------------------------------
# Endpoint management
# ---------------------------------------------------------------------------


def create_endpoint(
    *,
    workspace,
    actor,
    name: str,
    url: str,
    subscribed_event_types: list[str],
    request_id: str | None = None,
) -> tuple[WebhookEndpoint, str]:
    """Returns ``(endpoint, plaintext_secret)`` — the plaintext secret is
    returned exactly once, here, and never again (section 13)."""
    parse_webhook_url(url)  # raises WebhookInvalidURLError for structurally bad URLs
    _best_effort_ssrf_check(url)
    _validate_event_types(subscribed_event_types)

    plaintext_secret = generate_signing_secret()
    encrypted_secret = encrypt_credentials({"secret": plaintext_secret})
    now = timezone.now()
    with transaction.atomic():
        endpoint = WebhookEndpoint.objects.create(
            workspace=workspace,
            name=name[:MAX_NAME_LENGTH],
            url=url,
            subscribed_event_types=subscribed_event_types,
            encrypted_signing_secret=encrypted_secret,
            secret_created_at=now,
            created_by=actor,
        )
        record_event(
            action=AuditAction.WEBHOOK_ENDPOINT_CREATED,
            target_type="webhook_endpoint",
            target_id=endpoint.id,
            actor=actor,
            workspace=workspace,
            metadata={"name": endpoint.name, "event_types": subscribed_event_types},
            request_id=request_id,
        )
    return endpoint, plaintext_secret


def update_endpoint(
    *,
    workspace,
    endpoint: WebhookEndpoint,
    actor,
    name: str | None = None,
    url: str | None = None,
    subscribed_event_types: list[str] | None = None,
    request_id: str | None = None,
) -> WebhookEndpoint:
    update_fields: list[str] = []
    if name is not None:
        endpoint.name = name[:MAX_NAME_LENGTH]
        update_fields.append("name")
    if url is not None:
        parse_webhook_url(url)
        _best_effort_ssrf_check(url)
        endpoint.url = url
        update_fields.append("url")
    if subscribed_event_types is not None:
        _validate_event_types(subscribed_event_types)
        endpoint.subscribed_event_types = subscribed_event_types
        update_fields.append("subscribed_event_types")
    if not update_fields:
        return endpoint

    update_fields.append("updated_at")
    with transaction.atomic():
        endpoint.save(update_fields=update_fields)
        record_event(
            action=AuditAction.WEBHOOK_ENDPOINT_UPDATED,
            target_type="webhook_endpoint",
            target_id=endpoint.id,
            actor=actor,
            workspace=workspace,
            metadata={"fields": [f for f in update_fields if f != "updated_at"]},
            request_id=request_id,
        )
    return endpoint


def set_endpoint_status(
    *, workspace, endpoint: WebhookEndpoint, actor, status: str, request_id: str | None = None
) -> WebhookEndpoint:
    if status not in WebhookEndpointStatus.values:
        raise ValueError(f"Invalid webhook endpoint status: {status!r}")
    with transaction.atomic():
        endpoint.status = status
        endpoint.save(update_fields=["status", "updated_at"])
        record_event(
            action=(
                AuditAction.WEBHOOK_ENDPOINT_DISABLED
                if status == WebhookEndpointStatus.DISABLED
                else AuditAction.WEBHOOK_ENDPOINT_UPDATED
            ),
            target_type="webhook_endpoint",
            target_id=endpoint.id,
            actor=actor,
            workspace=workspace,
            metadata={"status": status},
            request_id=request_id,
        )
    return endpoint


def rotate_secret(
    *, workspace, endpoint: WebhookEndpoint, actor, request_id: str | None = None
) -> tuple[WebhookEndpoint, str]:
    """Returns ``(endpoint, plaintext_secret)`` — the new plaintext secret,
    once (section 14). Any delivery already pending for this endpoint signs
    with whatever secret is active at actual send time (section 35) — the
    event body itself is unaffected, since it was already frozen at
    ``WebhookEvent`` creation."""
    plaintext_secret = generate_signing_secret()
    encrypted_secret = encrypt_credentials({"secret": plaintext_secret})
    with transaction.atomic():
        endpoint.encrypted_signing_secret = encrypted_secret
        endpoint.secret_created_at = timezone.now()
        endpoint.save(update_fields=["encrypted_signing_secret", "secret_created_at", "updated_at"])
        record_event(
            action=AuditAction.WEBHOOK_SECRET_ROTATED,
            target_type="webhook_endpoint",
            target_id=endpoint.id,
            actor=actor,
            workspace=workspace,
            metadata={},
            request_id=request_id,
        )
    return endpoint, plaintext_secret


def _current_secret(endpoint: WebhookEndpoint) -> str:
    if not endpoint.encrypted_signing_secret:
        raise WebhookSigningNotConfiguredError()
    try:
        data = decrypt_credentials(endpoint.encrypted_signing_secret)
    except CredentialEncryptionError as exc:
        raise WebhookSigningNotConfiguredError() from exc
    secret = data.get("secret")
    if not secret or not isinstance(secret, str):
        raise WebhookSigningNotConfiguredError()
    return secret


# ---------------------------------------------------------------------------
# Event production / fanout (section 10-11)
# ---------------------------------------------------------------------------


def build_event_envelope(event: WebhookEvent) -> dict:
    """Explicit envelope builder (section 7) — never ``model.__dict__``,
    never an arbitrary ORM relation. ``id``/``created_at`` come from the
    event row itself; only ``data`` is the caller-supplied safe snapshot."""
    return {
        "id": str(event.id),
        "type": event.event_type,
        "version": event.version,
        "created_at": event.created_at.isoformat(),
        "workspace_id": str(event.workspace_id),
        "data": event.payload_snapshot,
    }


def emit_event(*, workspace, event_type: str, data: dict, version: int = 1) -> WebhookEvent:
    """Persist one immutable ``WebhookEvent`` and fan it out to every ACTIVE
    endpoint in this workspace subscribed to ``event_type`` (section 10-11).
    ``event_type`` is never client input — every caller passes a literal
    ``WebhookEventType`` value from an existing domain service's own call
    site (section 47); a value outside the allowlist is a programming
    error, not a normal runtime condition.

    Webhook delivery/fanout failure must never roll back the domain
    transaction that produced this event — this function performs its own
    persistence and commits before any network I/O is even scheduled
    (``create_delivery`` dispatches only after this whole block commits).
    """
    if event_type not in selectors.valid_event_types():
        raise WebhookInvalidEventTypeError(f"Unknown webhook event type: {event_type!r}")

    with transaction.atomic():
        event = WebhookEvent.objects.create(
            workspace=workspace, event_type=event_type, version=version, payload_snapshot=data
        )
        endpoints = list(
            selectors.active_endpoints_subscribed_to(workspace=workspace, event_type=event_type)
        )
        for endpoint in endpoints:
            delivery = create_delivery(workspace=workspace, channel=DeliveryChannel.WEBHOOK)
            try:
                WebhookDelivery.objects.create(
                    delivery=delivery, workspace=workspace, endpoint=endpoint, event=event
                )
            except IntegrityError:  # pragma: no cover - defensive, see model docstring
                # Lost a race for the (endpoint, event) uniqueness slot —
                # another concurrent emit_event call already created the
                # logical delivery for this pair; never a second one.
                continue
    return event


# ---------------------------------------------------------------------------
# Manual redrive (Phase 10 Block 4, section 28-37)
# ---------------------------------------------------------------------------


def redrive_webhook_delivery(
    *, workspace, webhook_delivery: WebhookDelivery, actor, request_id: str | None = None
) -> WebhookDelivery:
    """Manual redrive for an exhausted (``FAILED``/``DEAD``) webhook
    delivery. Reuses the exact same logical ``WebhookEvent``/``WebhookDelivery``
    /``Delivery`` row (section 30) — never creates a second event merely to
    redrive, and never resets ``attempt_count`` or erases attempt history.
    Grants a bounded number of additional attempts by raising
    ``Delivery.max_attempts`` (section 31, the repository-suggested option
    for this data model) so the next attempt continues the same monotonic
    numbering the ``attempt_count <= max_attempts`` constraint already
    enforces.

    Endpoint status is checked *before* any delivery-state change (section
    37): a disabled endpoint never produces a network call from redrive, and
    the row is left exactly as it was rather than flipped back to PENDING
    first. The next actual attempt still independently re-resolves DNS/SSRF
    and re-signs with whatever secret is active then (section 32) — nothing
    here bypasses ``handle_webhook_delivery_attempt``.
    """
    endpoint = WebhookEndpoint.objects.get(pk=webhook_delivery.endpoint_id)
    if endpoint.status != WebhookEndpointStatus.ACTIVE:
        raise WebhookEndpointDisabledError()

    with transaction.atomic():
        # Row-locked (section 35): an actively CLAIMED delivery, one that
        # already reached DELIVERED (section 36), or one still
        # PENDING/RETRY_SCHEDULED on its own is never redriven — only a
        # terminal, exhausted delivery is.
        locked = Delivery.objects.select_for_update().get(pk=webhook_delivery.delivery_id)
        if locked.status not in (DeliveryStatus.FAILED, DeliveryStatus.DEAD):
            raise WebhookDeliveryNotRedrivableError()
        locked.max_attempts = locked.max_attempts + settings.WEBHOOKS_REDRIVE_ATTEMPT_ALLOWANCE
        locked.status = DeliveryStatus.PENDING
        locked.next_attempt_at = timezone.now()
        locked.failed_at = None
        locked.save(
            update_fields=["max_attempts", "status", "next_attempt_at", "failed_at", "updated_at"]
        )
        record_event(
            action=AuditAction.WEBHOOK_DELIVERY_REDRIVEN,
            target_type="webhook_delivery",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"endpoint_id": str(endpoint.id)},
            request_id=request_id,
        )
        transaction.on_commit(partial(dispatch_delivery_for_processing, locked.id))
    return webhook_delivery


# ---------------------------------------------------------------------------
# Celery-boundary channel handler (section 33-34)
# ---------------------------------------------------------------------------


def handle_webhook_delivery_attempt(*, delivery: Delivery, claim_token: uuid.UUID) -> None:
    """The registered ``DeliveryChannel.WEBHOOK`` handler. Never bypasses
    Block 1's ownership-aware completion services — every exit path
    completes through ``complete_delivery_success`` /
    ``complete_delivery_failure``, both of which re-verify ``claim_token``.
    """
    webhook_delivery = (
        WebhookDelivery.objects.select_related("endpoint", "event")
        .filter(delivery=delivery)
        .first()
    )
    if webhook_delivery is None:
        complete_delivery_failure(
            delivery_id=delivery.id,
            claim_token=claim_token,
            safe_error_code=MISSING_WEBHOOK_DELIVERY_ERROR_CODE,
            retryable=False,
        )
        return

    # Reloaded fresh, never the possibly-stale ``select_related`` copy
    # above (section 34): a disabled endpoint must never begin a new
    # attempt, and status may have changed after this delivery was queued.
    endpoint = WebhookEndpoint.objects.get(pk=webhook_delivery.endpoint_id)
    if endpoint.status != WebhookEndpointStatus.ACTIVE:
        # This attempt slot was already consumed by the claim that got us
        # here (Block 1/2's claim-then-dispatch architecture creates the
        # DeliveryAttempt row before any handler runs) — there is no way to
        # "un-consume" it from inside the handler. What this check *does*
        # guarantee is that no network attempt to the endpoint occurs.
        complete_delivery_failure(
            delivery_id=delivery.id,
            claim_token=claim_token,
            safe_error_code=WebhookEndpointDisabledError.code,
            retryable=False,
        )
        return

    event = webhook_delivery.event
    try:
        secret = _current_secret(endpoint)
        parsed = parse_webhook_url(endpoint.url)
        # DNS resolved and validated fresh, every attempt (section 23) —
        # never trusting a value cached from endpoint creation or a prior
        # attempt.
        ip = resolve_and_validate(parsed.hostname, parsed.port)
        envelope = build_event_envelope(event)
        signed = build_signed_request(
            secret=secret,
            envelope=envelope,
            event_id=str(event.id),
            delivery_id=str(delivery.id),
        )
        result = send_pinned_request(
            scheme=parsed.scheme,
            ip=ip,
            port=parsed.port,
            hostname=parsed.hostname,
            path_and_query=parsed.path_and_query,
            headers=signed.headers,
            body=signed.raw_body,
        )
    except WebhookError as exc:
        complete_delivery_failure(
            delivery_id=delivery.id,
            claim_token=claim_token,
            safe_error_code=exc.code,
            retryable=exc.retryable,
        )
        return
    except (
        Exception
    ) as exc:  # noqa: BLE001 - untrusted transport boundary, see notification_delivery.py
        # Same Block 2 remediation rule (section 32): never log str(exc),
        # repr(exc), exc.args, or a traceback for an untrusted exception —
        # only stable, safe metadata.
        logger.error(
            "webhook_delivery_unexpected_error",
            extra={
                "event": "webhook_delivery_unexpected_error",
                "workspace_id": str(delivery.workspace_id),
                "delivery_id": str(delivery.id),
                "endpoint_id": str(endpoint.id),
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

    if 200 <= result.status_code <= 299:
        complete_delivery_success(
            delivery_id=delivery.id,
            claim_token=claim_token,
            response_status_code=result.status_code,
        )
        return
    retryable, safe_error_code = classify_http_status(result.status_code)
    complete_delivery_failure(
        delivery_id=delivery.id,
        claim_token=claim_token,
        safe_error_code=safe_error_code,
        retryable=retryable,
        response_status_code=result.status_code,
    )
