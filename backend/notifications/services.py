"""Durable delivery services (Phase 10 Block 1, extended in Block 2).

Every state transition below re-reads the target row under
``select_for_update`` inside a transaction before writing — the same pattern
``approvals/services.py`` and ``tools/execution.py`` already use for exactly
this reason: it is what makes concurrent claim/complete/reclaim races safe
against real PostgreSQL locking rather than in-process assumptions.

Claiming uses ``select_for_update(skip_locked=True)``: a worker racing
another for the same row never blocks waiting for it — it simply finds no
claimable row and returns a safe "not claimable" outcome (section 8, 20).
Ownership at completion time is proven by comparing the caller's
``claim_token`` against the delivery's *current* persisted token, not by
trusting anything held in a Celery task's memory (section 7, 15).

Block 2 adds best-effort Celery dispatch after commit (section 9-10) and
replaces the Block 1 placeholder task body with a real per-channel handler
dispatch (section 4) — see ``process_claimed_delivery`` below.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from functools import partial

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .backoff import compute_retry_delay_seconds
from .errors import DeliveryNotClaimableError, DeliveryNotFoundError, StaleClaimError
from .models import AttemptStatus, Delivery, DeliveryAttempt, DeliveryStatus

logger = logging.getLogger("supportpilot")

MAX_SAFE_ERROR_CODE_LENGTH = 64


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


def create_delivery(
    *, workspace, channel: str, max_attempts: int | None = None, now=None
) -> Delivery:
    """Create a new, immediately-due delivery and best-effort dispatch it for
    processing once (and only once) this transaction commits (section 9).
    ``max_attempts`` is a server-configured value only (section 13) — no
    client, model, or LLM caller of this function may ever originate that
    value from untrusted input; it is either omitted (server default) or set
    by trusted internal configuration."""
    now = now or timezone.now()
    max_attempts = (
        max_attempts if max_attempts is not None else settings.DELIVERY_DEFAULT_MAX_ATTEMPTS
    )
    with transaction.atomic():
        delivery = Delivery.objects.create(
            workspace=workspace,
            channel=channel,
            max_attempts=max_attempts,
            next_attempt_at=now,
        )
        # Broker publication is best-effort (section 9-10): if it fails, the
        # row above is already committed and stays PENDING/due — recoverable
        # by Block 4's sweeper — rather than being rolled back merely
        # because Redis/the broker was unavailable at this instant.
        transaction.on_commit(partial(dispatch_delivery_for_processing, delivery.id))
    logger.info(
        "delivery_created",
        extra={
            "event": "delivery_created",
            "workspace_id": str(workspace.id),
            "delivery_id": str(delivery.id),
            "channel": channel,
        },
    )
    return delivery


def dispatch_delivery_for_processing(delivery_id: uuid.UUID | str) -> None:
    """Best-effort Celery publication (section 9-10) — the single publication
    primitive shared by initial creation (``create_delivery``), the Block 4
    due-work/expired-claim recovery sweepers, and manual webhook redrive.
    Publishing the same delivery id more than once (two sweepers, a sweep
    racing an active worker, a redrive racing a sweep) is always safe:
    publication is not itself an ownership operation — only
    ``claim_delivery``/``reclaim_expired_delivery`` inside
    ``process_claimed_delivery`` decide who actually gets to attempt it
    (section 10).

    A broker failure here must never: delete the delivery, mark it as a
    provider failure, consume an attempt slot, or expose a raw Celery/Kombu
    exception — it only means nobody woke up a worker immediately; the
    delivery is already persisted and due, so the next sweep can still find
    and claim it later."""
    from common.correlation import get_correlation_id

    from .tasks import process_delivery_task

    logger.info(
        "delivery_dispatch_attempted",
        extra={"event": "delivery_dispatch_attempted", "delivery_id": str(delivery_id)},
    )
    try:
        process_delivery_task.delay(str(delivery_id), correlation_id=get_correlation_id())
    except Exception:  # noqa: BLE001 - broker/transport errors are unbounded in type
        logger.warning(
            "delivery_dispatch_failed",
            extra={"event": "delivery_dispatch_failed", "delivery_id": str(delivery_id)},
        )


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------


def _due_eligible(delivery: Delivery, now) -> bool:
    return (
        delivery.status in (DeliveryStatus.PENDING, DeliveryStatus.RETRY_SCHEDULED)
        and delivery.next_attempt_at <= now
    )


def _expired_claim_eligible(delivery: Delivery, now) -> bool:
    return (
        delivery.status == DeliveryStatus.CLAIMED
        and delivery.lease_expires_at is not None
        and delivery.lease_expires_at <= now
    )


def _claim_row(
    *,
    delivery_id: uuid.UUID | str,
    eligible: Callable[[Delivery, object], bool],
    lease_seconds: int | None,
    now,
) -> tuple[Delivery, uuid.UUID]:
    lease_seconds = (
        lease_seconds if lease_seconds is not None else settings.DELIVERY_CLAIM_LEASE_SECONDS
    )
    with transaction.atomic():
        # skip_locked=True is the concurrency primitive (section 8): a
        # worker that loses the race for this row never blocks on the
        # winner's transaction — it simply sees no row here and falls
        # through to the safe "not claimable" outcome below.
        locked = Delivery.objects.select_for_update(skip_locked=True).filter(pk=delivery_id).first()
        if locked is None or not eligible(locked, now):
            raise DeliveryNotClaimableError()
        next_attempt_number = locked.attempt_count + 1
        if next_attempt_number > locked.max_attempts:
            # Defensive: a correctly-scheduled delivery never reaches this —
            # exhaustion is decided at completion time (see
            # complete_delivery_failure) before a delivery is ever left
            # claimable again.
            raise DeliveryNotClaimableError()

        if locked.status == DeliveryStatus.CLAIMED and locked.claim_token is not None:
            # Only true on the expired-claim recovery path (plain
            # claim_delivery only ever matches PENDING/RETRY_SCHEDULED rows,
            # which the claim-field-consistency constraint guarantees carry
            # no claim_token). The abandoned worker's in-flight attempt is
            # explicitly marked rather than left ambiguously "in_progress"
            # forever (section 15) — its eventual completion call is
            # independently rejected by StaleClaimError regardless.
            DeliveryAttempt.objects.filter(
                delivery=locked, claim_token=locked.claim_token, status=AttemptStatus.IN_PROGRESS
            ).update(status=AttemptStatus.ABANDONED, completed_at=now, updated_at=now)

        token = uuid.uuid4()
        locked.status = DeliveryStatus.CLAIMED
        locked.claim_token = token
        locked.claimed_at = now
        locked.lease_expires_at = now + timedelta(seconds=lease_seconds)
        if locked.first_attempt_at is None:
            locked.first_attempt_at = now
        locked.attempt_count = next_attempt_number
        locked.save(
            update_fields=[
                "status",
                "claim_token",
                "claimed_at",
                "lease_expires_at",
                "first_attempt_at",
                "attempt_count",
                "updated_at",
            ]
        )
        DeliveryAttempt.objects.create(
            delivery=locked,
            attempt_number=next_attempt_number,
            claim_token=token,
            status=AttemptStatus.IN_PROGRESS,
            started_at=now,
        )
    logger.info(
        "delivery_claimed",
        extra={
            "event": "delivery_claimed",
            "workspace_id": str(locked.workspace_id),
            "delivery_id": str(locked.id),
            "attempt_number": next_attempt_number,
            "status": locked.status,
        },
    )
    return locked, token


def claim_delivery(
    *, delivery_id: uuid.UUID | str, lease_seconds: int | None = None, now=None
) -> tuple[Delivery, uuid.UUID]:
    """Claim a due PENDING/RETRY_SCHEDULED delivery. Raises
    ``DeliveryNotClaimableError`` (a safe, expected outcome — never an
    operational error) if the row is missing, not due yet, already actively
    claimed, or terminal."""
    now = now or timezone.now()
    return _claim_row(
        delivery_id=delivery_id, eligible=_due_eligible, lease_seconds=lease_seconds, now=now
    )


def reclaim_expired_delivery(
    *, delivery_id: uuid.UUID | str, lease_seconds: int | None = None, now=None
) -> tuple[Delivery, uuid.UUID]:
    """Reclaim a CLAIMED delivery whose lease has expired — the stale-worker
    recovery path (section 7, 9, 21). Issues a brand-new ``claim_token``;
    the original worker's token becomes unconditionally stale (see
    ``_assert_active_claim`` below)."""
    now = now or timezone.now()
    return _claim_row(
        delivery_id=delivery_id,
        eligible=_expired_claim_eligible,
        lease_seconds=lease_seconds,
        now=now,
    )


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


def _lock_delivery_or_raise(delivery_id: uuid.UUID | str) -> Delivery:
    try:
        return Delivery.objects.select_for_update().get(pk=delivery_id)
    except Delivery.DoesNotExist as exc:
        raise DeliveryNotFoundError() from exc


def _assert_active_claim(delivery: Delivery, claim_token: uuid.UUID | str) -> None:
    """The single ownership-proof check (section 15): a completion call only
    ever succeeds if the delivery is still CLAIMED under exactly this token.
    A stale worker (expired lease, already reclaimed or already completed by
    someone else) always lands here instead of overwriting newer state."""
    if delivery.status != DeliveryStatus.CLAIMED or str(delivery.claim_token) != str(claim_token):
        raise StaleClaimError()


def _complete_active_attempt(
    *,
    delivery: Delivery,
    claim_token: uuid.UUID | str,
    status: str,
    safe_error_code: str,
    retryable: bool | None,
    now,
    response_status_code: int | None = None,
) -> DeliveryAttempt:
    attempt = DeliveryAttempt.objects.get(
        delivery=delivery, claim_token=claim_token, status=AttemptStatus.IN_PROGRESS
    )
    attempt.status = status
    attempt.completed_at = now
    attempt.latency_ms = max(int((now - attempt.started_at).total_seconds() * 1000), 0)
    attempt.safe_error_code = safe_error_code[:MAX_SAFE_ERROR_CODE_LENGTH]
    attempt.retryable = retryable
    update_fields = [
        "status",
        "completed_at",
        "latency_ms",
        "safe_error_code",
        "retryable",
        "updated_at",
    ]
    if response_status_code is not None:
        # Reserved since Block 1 specifically for this (section 10 of that
        # block) — only ever populated by an HTTP-based channel handler
        # (webhooks, Block 3); notification delivery never sets it.
        attempt.response_status_code = response_status_code
        update_fields.append("response_status_code")
    attempt.save(update_fields=update_fields)
    return attempt


def complete_delivery_success(
    *,
    delivery_id: uuid.UUID | str,
    claim_token: uuid.UUID | str,
    now=None,
    response_status_code: int | None = None,
) -> Delivery:
    now = now or timezone.now()
    with transaction.atomic():
        locked = _lock_delivery_or_raise(delivery_id)
        _assert_active_claim(locked, claim_token)
        _complete_active_attempt(
            delivery=locked,
            claim_token=claim_token,
            status=AttemptStatus.SUCCEEDED,
            safe_error_code="",
            retryable=None,
            now=now,
            response_status_code=response_status_code,
        )
        locked.status = DeliveryStatus.DELIVERED
        locked.delivered_at = now
        locked.claim_token = None
        locked.claimed_at = None
        locked.lease_expires_at = None
        locked.save(
            update_fields=[
                "status",
                "delivered_at",
                "claim_token",
                "claimed_at",
                "lease_expires_at",
                "updated_at",
            ]
        )
    logger.info(
        "delivery_succeeded",
        extra={
            "event": "delivery_succeeded",
            "workspace_id": str(locked.workspace_id),
            "delivery_id": str(locked.id),
            "attempt_number": locked.attempt_count,
            "status": locked.status,
        },
    )
    return locked


def complete_delivery_failure(
    *,
    delivery_id: uuid.UUID | str,
    claim_token: uuid.UUID | str,
    safe_error_code: str,
    retryable: bool,
    retry_delay_seconds: int | None = None,
    now=None,
    response_status_code: int | None = None,
) -> Delivery:
    """A retryable failure with attempts remaining is scheduled using
    deterministic bounded exponential backoff (Phase 10 Block 4, section 4-5)
    keyed off the just-failed attempt's own number — never a Celery retry
    counter (section 3); anything else terminates the delivery, split into
    FAILED (retries exhausted) vs. DEAD (explicitly non-retryable, section 6)
    so a future replay tool can distinguish the two. ``retry_delay_seconds``
    remains available as an explicit override (existing callers, deterministic
    tests) — when omitted, the backoff schedule below computes it."""
    now = now or timezone.now()
    with transaction.atomic():
        locked = _lock_delivery_or_raise(delivery_id)
        _assert_active_claim(locked, claim_token)
        _complete_active_attempt(
            delivery=locked,
            claim_token=claim_token,
            status=AttemptStatus.FAILED,
            safe_error_code=safe_error_code,
            retryable=retryable,
            now=now,
            response_status_code=response_status_code,
        )
        locked.last_error_code = safe_error_code[:MAX_SAFE_ERROR_CODE_LENGTH]
        locked.claim_token = None
        locked.claimed_at = None
        locked.lease_expires_at = None
        can_retry = retryable and locked.attempt_count < locked.max_attempts
        if can_retry:
            delay_seconds = (
                retry_delay_seconds
                if retry_delay_seconds is not None
                else compute_retry_delay_seconds(attempt_number=locked.attempt_count)
            )
            locked.status = DeliveryStatus.RETRY_SCHEDULED
            locked.next_attempt_at = now + timedelta(seconds=delay_seconds)
        else:
            locked.status = DeliveryStatus.FAILED if retryable else DeliveryStatus.DEAD
            locked.failed_at = now
        locked.save(
            update_fields=[
                "last_error_code",
                "claim_token",
                "claimed_at",
                "lease_expires_at",
                "status",
                "next_attempt_at",
                "failed_at",
                "updated_at",
            ]
        )
    logger.info(
        "delivery_failed",
        extra={
            "event": "delivery_failed",
            "workspace_id": str(locked.workspace_id),
            "delivery_id": str(locked.id),
            "attempt_number": locked.attempt_count,
            "status": locked.status,
            "safe_error_code": safe_error_code[:MAX_SAFE_ERROR_CODE_LENGTH],
        },
    )
    return locked


# ---------------------------------------------------------------------------
# Celery task boundary (section 19-20; Block 2 section 4, 14)
# ---------------------------------------------------------------------------


def process_claimed_delivery(delivery_id: str) -> str:
    """The entire body the Celery task delegates to (section 19: no domain
    logic in the task itself). Resolves the registered handler for
    ``Delivery.channel`` and calls it with an already-claimed delivery +
    claim token; the handler is solely responsible for the external attempt
    and completing the delivery through the ownership-aware service
    functions above (section 14).

    ``channel`` is read *before* claiming so a genuinely unregistered
    channel is detected without consuming a claim/attempt slot (section 4)
    — safe because ``channel`` is immutable after creation, never touched by
    any service in this module. Duplicate task delivery is safe: only the
    first invocation can claim; a redelivered task finds nothing claimable
    and no-ops (section 20).

    Block 4 (section 14, 19): a single publication of this task now covers
    both a due PENDING/RETRY_SCHEDULED delivery *and* a CLAIMED delivery
    whose lease has already expired — ``claim_delivery`` is tried first, and
    only on a safe "not claimable" outcome is ``reclaim_expired_delivery``
    tried as a fallback. This is what lets the recovery sweeper publish one
    task per delivery id regardless of which of the two recovery states it
    is in, without needing two different task bodies."""
    from .handlers import get_channel_handler

    channel = Delivery.objects.filter(pk=delivery_id).values_list("channel", flat=True).first()
    if channel is None:
        return "skipped"
    handler = get_channel_handler(channel)
    if handler is None:
        # An internal implementation gap (an unregistered channel) is never
        # turned into a fake provider failure against the delivery itself
        # (section 4) — it is surfaced only in operational logs, and the
        # delivery is left exactly as it was for once the channel is
        # registered (or for an operator to investigate).
        logger.warning(
            "delivery_channel_handler_missing",
            extra={"event": "delivery_channel_handler_missing", "channel": channel},
        )
        return "skipped_unsupported_channel"

    try:
        delivery, token = claim_delivery(delivery_id=delivery_id)
    except DeliveryNotClaimableError:
        try:
            delivery, token = reclaim_expired_delivery(delivery_id=delivery_id)
        except DeliveryNotClaimableError:
            return "skipped"
    handler(delivery=delivery, claim_token=token)
    return "processed"
