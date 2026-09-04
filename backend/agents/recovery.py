"""Stuck-worker recovery for ``AgentRun`` (Phase 16 Checkpoint 2 Part C).

Checkpoint 1 documented a real gap in
``docs/reliability/retry-recovery-and-concurrency.md``: unlike
``channel_ingress``/``notifications``, nothing ever finds an ``AgentRun``
left ``RUNNING`` by a worker that crashed mid-execution — with
``CELERY_TASK_ACKS_LATE`` unset and the task's ``max_retries=3`` inert (see
that doc's Retry model section), such a row is stuck forever with no
automated recovery path. This module closes the *logic* gap; wiring a
periodic Celery Beat schedule to call it is deliberately left to Phase 17
(see settings comment above ``AGENTS_STUCK_RUN_STALE_SECONDS``).

Design choice — recover by failing, never by re-executing: a ``RUNNING``
row's worker may already have called a tool with real-world side effects
(a refund, a booking) before it crashed. Silently re-dispatching the same
run risks duplicating that side effect with no idempotency boundary to
catch it (unlike ``channel_ingress``'s sweep, which only ever re-publishes
an *unclaimed* event id into the same claim-then-process boundary). The
smallest reliable primitive is therefore to transition the row to a
terminal, clearly-labelled failure state — never automatically retried —
leaving any actual re-attempt to an operator or a fresh, distinct run.

Staleness, not a heartbeat: no per-run lease/heartbeat exists yet, so
"no worker is making progress" is approximated by ``updated_at`` — every
step write (`_next_sequence_and_create_step` -> ``AgentStep.objects.create``
does not touch ``AgentRun.updated_at``, but every state-mutating call in
``agents/services.py`` does ``run.save()``, which does) advances it while a
real worker is alive. ``AGENTS_STUCK_RUN_STALE_SECONDS`` must exceed any
legitimate run's real wall-clock duration; this is intentionally coarse
until a per-run wall-time budget is exposed to the sweeper.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.models import AuditAction
from audit.services import record_event

from .models import (
    AgentRun,
    AgentRunStatus,
    AgentStepStatus,
    AgentStepType,
)

logger = logging.getLogger("supportpilot")


def recover_stuck_agent_runs(*, batch_size: int | None = None, now=None) -> int:
    """Fail ``AgentRun`` rows left ``RUNNING`` past the staleness threshold.

    Returns the number of runs actually recovered. Safe to call repeatedly
    and from multiple concurrent workers/schedulers: each candidate row is
    only ever recovered once (section 11 idempotency, race-safety below).
    """
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.AGENTS_STUCK_RUN_STALE_SECONDS)
    batch_size = (
        batch_size if batch_size is not None else settings.AGENTS_STUCK_RUN_SWEEP_BATCH_SIZE
    )
    run_ids = list(
        AgentRun.objects.filter(status=AgentRunStatus.RUNNING, updated_at__lte=cutoff)
        .order_by("updated_at")
        .values_list("id", flat=True)[:batch_size]
    )
    recovered = 0
    for run_id in run_ids:
        if _recover_one_stuck_run(run_id, cutoff=cutoff, now=now):
            recovered += 1
    if recovered:
        logger.info(
            "agents_stuck_run_recovered",
            extra={"event": "agents_stuck_run_recovered", "count": recovered},
        )
    return recovered


def _recover_one_stuck_run(run_id, *, cutoff, now) -> bool:
    """One row, one transaction, one lock — mirrors every other claim
    boundary in this codebase (``claim_agent_run``, ``_fail_run``, etc.).

    The re-check of both ``status`` and ``updated_at`` *after* the lock is
    acquired is what makes this race-safe against a still-active worker: if
    the worker legitimately wrote to this exact row (even a same-status
    heartbeat-style save) between the batch query above and this function
    acquiring the lock, ``updated_at`` has moved past ``cutoff`` and this is
    a genuine no-op — the current owner's result wins, and the "old worker
    later finalizes" direction cannot regress a row already recovered
    because recovery only ever transitions out of ``RUNNING`` into a
    terminal status, and every other transition function in
    ``agents/services.py`` already guards on ``status in
    AGENT_RUN_TERMINAL_STATUSES`` before writing.
    """
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run_id)
        if locked.status != AgentRunStatus.RUNNING:
            return False
        if locked.updated_at > cutoff:
            return False
        locked.status = AgentRunStatus.FAILED
        locked.failure_code = "stuck_worker_recovered"
        locked.failure_message_safe = (
            "Recovered: no worker progress was observed before the staleness threshold."
        )
        locked.completed_at = now
        locked.save()
        # Reuses the same run-scoped sequence assignment every other step
        # write in this app uses (``agents.services._next_sequence_and_create_step``)
        # rather than a second implementation of it.
        from .services import _next_sequence_and_create_step

        _next_sequence_and_create_step(
            locked,
            step_type=AgentStepType.RUN_FAILED,
            status=AgentStepStatus.FAILED,
            error_code="stuck_worker_recovered",
        )
        record_event(
            action=AuditAction.AGENT_RUN_FAILED,
            target_type="agent_run",
            target_id=locked.id,
            actor=locked.created_by,
            workspace=locked.workspace,
            metadata={"agent_run_id": str(locked.id), "failure_code": "stuck_worker_recovered"},
            request_id=locked.correlation_id or None,
        )
        _fail_in_flight_tool_executions(locked, now=now)
    return True


def _fail_in_flight_tool_executions(run: AgentRun, *, now) -> None:
    """A worker that crashed mid-run may also have left a child
    ``ToolExecution`` ``PENDING``/``RUNNING`` — orphaned along with the run
    it belongs to. Imported locally to avoid a module-level
    agents<->tools import cycle (matches ``cancel_agent_run``).

    A conditional ``.update()`` filtered back on the exact prior status is
    the same single-fire guard ``cancel_agent_run`` uses: this can never
    clobber an execution a still-active (not actually crashed, merely slow
    on this one row) caller already finalized between the query and here.
    """
    from tools.models import ToolExecution, ToolExecutionStatus

    ToolExecution.objects.filter(
        agent_run=run,
        status__in=(ToolExecutionStatus.PENDING, ToolExecutionStatus.RUNNING),
    ).update(
        status=ToolExecutionStatus.FAILED,
        error_code="stuck_worker_recovered",
        completed_at=now,
        updated_at=now,
    )
