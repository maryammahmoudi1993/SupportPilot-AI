"""Recovery sweeper (Phase 10 Block 4, section 9-22).

Two independent, bounded, DB-driven discovery passes. Neither performs any
external provider/network I/O itself (section 9) — both only re-publish a
delivery id for the existing claim-then-handle Celery boundary
(``notifications.services.process_claimed_delivery``) to pick up, exactly as
if a worker had just been woken by the original ``transaction.on_commit``
call. All correctness (who actually gets to attempt the delivery) comes from
that boundary's claim/reclaim primitives, never from anything in this module
(section 10) — republishing the same delivery id from two concurrent sweeps,
or from a sweep racing an already-active worker, is always safe.

Recovery state depends only on PostgreSQL (section 22, 55): this module reads
no in-memory queue, cache, or list of "deliveries seen before" — a freshly
started process calling either function below recovers exactly the same
candidate set a long-running one would.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from . import selectors
from .services import dispatch_delivery_for_processing

logger = logging.getLogger("supportpilot")


def dispatch_due_deliveries(*, batch_size: int | None = None, now=None) -> int:
    """Re-publish PENDING/RETRY_SCHEDULED deliveries whose ``next_attempt_at``
    has arrived (section 9, 12-13). Closes the original Phase 10 gap where a
    delivery's *only* publication attempt was the best-effort
    ``transaction.on_commit`` callback at creation time — if that single
    attempt was lost (broker outage), nothing would ever re-publish it
    without this sweep."""
    batch_size = batch_size if batch_size is not None else settings.DELIVERY_SWEEP_BATCH_SIZE
    now = now or timezone.now()
    delivery_ids = list(
        selectors.due_claimable_deliveries(now=now).values_list("id", flat=True)[:batch_size]
    )
    for delivery_id in delivery_ids:
        dispatch_delivery_for_processing(delivery_id)
    if delivery_ids:
        logger.info(
            "delivery_retry_due",
            extra={"event": "delivery_retry_due", "count": len(delivery_ids)},
        )
    return len(delivery_ids)


def recover_expired_delivery_claims(*, batch_size: int | None = None, now=None) -> int:
    """Re-publish CLAIMED deliveries whose lease has expired (section 14,
    21). The republished task claims via ``reclaim_expired_delivery``
    (see ``process_claimed_delivery``), which issues a fresh claim token,
    marks the abandoned worker's in-flight attempt ``ABANDONED``, and gives a
    new worker a clean attempt slot — the stale-worker fencing established in
    Block 1 (``StaleClaimError``) protects the delivery if the original
    worker eventually wakes up and tries to complete it anyway."""
    batch_size = batch_size if batch_size is not None else settings.DELIVERY_SWEEP_BATCH_SIZE
    now = now or timezone.now()
    delivery_ids = list(
        selectors.expired_claimed_deliveries(now=now).values_list("id", flat=True)[:batch_size]
    )
    for delivery_id in delivery_ids:
        dispatch_delivery_for_processing(delivery_id)
    if delivery_ids:
        logger.info(
            "delivery_claim_recovered",
            extra={"event": "delivery_claim_recovered", "count": len(delivery_ids)},
        )
    return len(delivery_ids)
