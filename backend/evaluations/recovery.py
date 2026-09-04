"""Stuck-worker recovery for evaluation runs/cases (Phase 16 Checkpoint 2
Part C). Mirrors ``agents/recovery.py``'s design choice and rationale —
recover by failing, never by re-executing (a case handler may already have
called a real tool with side effects before its worker crashed).

The stuck unit here is actually the *case* (``EvaluationResult``), not the
run: ``EvaluationRun.status`` only ever advances via
``evaluations.services._record_case_completion``, which is called by a case
finishing — a case a worker crashed while executing never calls it, so the
run's own ``updated_at`` also freezes (nothing else writes to the run row
while it waits) and it can look "stuck" purely as a side effect of its
cases never finishing. This module therefore recovers stale ``RUNNING``
cases first, then recomputes+finalizes the run from the (now corrected)
case set — reusing ``_aggregate_case_counts``/``finalize_evaluation_run``
rather than a second implementation of run-counter arithmetic, so the
"deterministic tie-breaker"/"same snapshot" guarantees Checkpoint 1 built
for those functions apply here unchanged.

Lock ordering matches every other multi-row lock in this module (Part D):
Run is always locked before Result.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from observability.metrics import observe_stuck_run_recovery

from .models import (
    EvaluationFailureCode,
    EvaluationResult,
    EvaluationResultStatus,
    EvaluationRun,
    EvaluationRunStatus,
)

logger = logging.getLogger("supportpilot")


def recover_stuck_evaluation_runs(*, batch_size: int | None = None, now=None) -> int:
    """Recover ``EvaluationRun`` rows left ``RUNNING`` past the staleness
    threshold: fail any of that run's stale ``RUNNING`` cases, then
    recompute and (if now complete) finalize the run. Returns the number of
    runs actually touched. Safe to call repeatedly/concurrently — see
    ``_recover_one_stuck_run``."""
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.EVALUATIONS_STUCK_RUN_STALE_SECONDS)
    batch_size = (
        batch_size if batch_size is not None else settings.EVALUATIONS_STUCK_RUN_SWEEP_BATCH_SIZE
    )
    run_ids = list(
        EvaluationRun.objects.filter(status=EvaluationRunStatus.RUNNING, updated_at__lte=cutoff)
        .order_by("updated_at")
        .values_list("id", flat=True)[:batch_size]
    )
    recovered = 0
    for run_id in run_ids:
        if _recover_one_stuck_run(run_id, cutoff=cutoff, now=now):
            recovered += 1
    if recovered:
        logger.info(
            "evaluations_stuck_run_recovered",
            extra={"event": "evaluations_stuck_run_recovered", "count": recovered},
        )
        observe_stuck_run_recovery(domain="evaluation", count=recovered)
    return recovered


def _recover_one_stuck_run(run_id, *, cutoff, now) -> bool:
    """One run, one transaction, lock Run before Result (Part D). The
    re-check of ``status``/``updated_at`` after the lock is acquired makes
    this race-safe against a still-active worker exactly like
    ``agents.recovery._recover_one_stuck_run``: if the run genuinely made
    progress (a case completed, advancing ``updated_at`` via
    ``_record_case_completion``) between the batch query and this lock, this
    is a no-op. Recovering a run twice is also a no-op — the second pass's
    stale-``RUNNING``-cases query returns nothing to fail, and
    ``finalize_evaluation_run`` itself only transitions a currently-RUNNING
    run, so a run already finalized by the first pass or a concurrent
    ``cancel_evaluation_run`` is left untouched.

    Phase 16 Checkpoint 3 (Part A): ``EvaluationRun.updated_at`` only ever
    advances at claim time and again whenever *any* case completes
    (``_record_case_completion`` saves the run row) — never while a case is
    merely still executing. A run with many cases, run through limited
    worker concurrency, can therefore legitimately go longer than
    ``EVALUATIONS_STUCK_RUN_STALE_SECONDS`` between case completions purely
    because the currently in-flight case hasn't finished yet, not because
    anything crashed. Distinguishing "genuinely stuck" from "no case has
    completed *recently*, but one is still legitimately running" cannot be
    done from the run's own ``updated_at`` alone — the correct, already-
    authoritative liveness signal is each case's own ``updated_at`` (touched
    at claim and again at completion). A run is only ever a genuine recovery
    candidate if it has no such live case: at least one non-terminal case
    whose own row is not yet stale means the run itself is not stuck, and
    this sweep must leave it alone entirely — no case is failed, no counters
    are recomputed, and the run row is not touched (a synthetic touch-only
    write would itself be a fake heartbeat, which this checkpoint's guidance
    explicitly rules out; the case-level ``updated_at`` this reads is
    already-existing state, not a new heartbeat mechanism).
    """
    from .services import _aggregate_case_counts, finalize_evaluation_run

    with transaction.atomic():
        run = EvaluationRun.objects.select_for_update().get(pk=run_id)
        if run.status != EvaluationRunStatus.RUNNING:
            return False
        if run.updated_at > cutoff:
            return False
        live_case_exists = EvaluationResult.objects.filter(
            run=run,
            status=EvaluationResultStatus.RUNNING,
            replay_of__isnull=True,
            updated_at__gt=cutoff,
        ).exists()
        stale_result_ids = list(
            EvaluationResult.objects.select_for_update()
            .filter(
                run=run,
                status=EvaluationResultStatus.RUNNING,
                replay_of__isnull=True,
                updated_at__lte=cutoff,
            )
            .values_list("id", flat=True)
        )
        if not stale_result_ids and live_case_exists:
            # Nothing to fail, and a case is genuinely still in flight — this
            # run is healthy and making progress, not stuck. Leave it
            # completely untouched and do not count it as a recovery event.
            return False
        if stale_result_ids:
            EvaluationResult.objects.filter(
                id__in=stale_result_ids, status=EvaluationResultStatus.RUNNING
            ).update(
                status=EvaluationResultStatus.FAILED,
                passed=False,
                failure_code=EvaluationFailureCode.WORKER_CRASH_RECOVERED,
                failure_message_safe=(
                    "Recovered: worker did not finalize this case before the staleness "
                    "threshold."
                ),
                completed_at=now,
                updated_at=now,
            )
        # Otherwise: no stale RUNNING case and no live one either (e.g.
        # every case is still PENDING/never claimed, or all are already
        # terminal and only the run's own finalize step was lost) — fall
        # through to recompute+finalize below exactly as before; this is the
        # existing "completed case not clobbered" / "run finalize was lost"
        # recovery path, unchanged.
        run.completed_cases, run.passed_cases = _aggregate_case_counts(run)
        run.failed_cases = run.completed_cases - run.passed_cases
        run.save()
    if run.completed_cases >= run.total_cases:
        finalize_evaluation_run(run_id)
    return True
