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
    """
    from .services import _aggregate_case_counts, finalize_evaluation_run

    with transaction.atomic():
        run = EvaluationRun.objects.select_for_update().get(pk=run_id)
        if run.status != EvaluationRunStatus.RUNNING:
            return False
        if run.updated_at > cutoff:
            return False
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
        run.completed_cases, run.passed_cases = _aggregate_case_counts(run)
        run.failed_cases = run.completed_cases - run.passed_cases
        run.save()
    if run.completed_cases >= run.total_cases:
        finalize_evaluation_run(run_id)
    return True
