"""Stuck-worker recovery for ``AgentRun`` (Phase 16 Checkpoint 2 Part C).

Checkpoint 1 documented a real gap in
``docs/reliability/retry-recovery-and-concurrency.md``: unlike
``channel_ingress``/``notifications``, nothing ever finds an ``AgentRun``
left ``RUNNING`` by a worker that crashed mid-execution — with
``CELERY_TASK_ACKS_LATE`` unset and the task's ``max_retries=3`` inert (see
that doc's Retry model section), such a row is stuck forever with no
automated recovery path. This module holds the recovery *logic*; the
periodic Celery Beat schedule that calls it lives in
``agents.tasks.recover_stuck_agent_runs_task`` and
``config/celery.py``'s ``beat_schedule`` (Phase 17).

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
from observability.metrics import observe_stuck_run_recovery

from .models import (
    AgentRun,
    AgentRunStatus,
    AgentStepStatus,
    AgentStepType,
)

logger = logging.getLogger("supportpilot")


def recover_stuck_agent_runs(*, batch_size: int | None = None, now=None) -> int:
    """Fail ``AgentRun`` rows left ``RUNNING`` past the staleness threshold,
    re-publish rows left ``PENDING`` past a much shorter threshold, and
    re-publish rows left ``WAITING_FOR_APPROVAL`` whose gating approval is
    already decided (Phase 17 final acceptance gate, Part B — see
    ``_redispatch_stuck_pending_runs``/``_redispatch_stuck_waiting_for_approval_runs``
    for why these are distinct, and distinctly safer, recoveries than the
    RUNNING case).

    Returns the number of runs actually recovered/re-published. Safe to call
    repeatedly and from multiple concurrent workers/schedulers: each
    candidate row is only ever recovered once (section 11 idempotency,
    race-safety below).
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
        observe_stuck_run_recovery(domain="agent", count=recovered)
    recovered += _redispatch_stuck_pending_runs(batch_size=batch_size, now=now)
    recovered += _redispatch_stuck_waiting_for_approval_runs(batch_size=batch_size, now=now)
    return recovered


def _redispatch_stuck_waiting_for_approval_runs(*, batch_size: int, now) -> int:
    """A decision (approve/reject/expire) dispatches
    ``resume_approved_action_task`` via its own ``transaction.on_commit`` —
    if that single publish is lost, the ``AgentRun`` stays
    ``WAITING_FOR_APPROVAL`` forever even though the gating
    ``ApprovalRequest`` already reached a terminal decision, and no manual
    API path exists to re-decide an already-resolved approval. Re-publishing
    is safe: ``agents.services._claim_run_for_resume`` makes a
    second/redelivered resume call a no-op (see
    ``approvals/tasks.py``'s docstring). Deliberately excludes ``cancelled``
    approvals — those are the terminal outcome of the *run itself* already
    being cancelled through a different path (``cancel_approval_for_execution``
    never dispatches a resume), so there is nothing to redispatch for one.
    """
    from approvals.models import ApprovalStatus

    pending_cutoff = now - timedelta(
        seconds=settings.AGENTS_STUCK_RUN_WAITING_FOR_APPROVAL_STALE_SECONDS
    )
    candidates = list(
        AgentRun.objects.filter(
            status=AgentRunStatus.WAITING_FOR_APPROVAL,
            tool_executions__approval_request__status__in=(
                ApprovalStatus.APPROVED,
                ApprovalStatus.REJECTED,
                ApprovalStatus.EXPIRED,
            ),
            tool_executions__approval_request__resolved_at__lte=pending_cutoff,
        )
        .order_by("updated_at")
        .values_list("tool_executions__approval_request__id", flat=True)[:batch_size]
    )
    for approval_id in candidates:
        _redispatch_resume(approval_id)
    if candidates:
        logger.info(
            "agents_stuck_waiting_for_approval_run_redispatched",
            extra={
                "event": "agents_stuck_waiting_for_approval_run_redispatched",
                "count": len(candidates),
            },
        )
        observe_stuck_run_recovery(domain="agent_approval_resume_dispatch", count=len(candidates))
    return len(candidates)


def _redispatch_resume(approval_id) -> None:
    from approvals.services import _dispatch_resume

    _dispatch_resume(approval_id)


def _redispatch_stuck_pending_runs(*, batch_size: int, now) -> int:
    """A run's *only* initial publish is the ``transaction.on_commit``
    ``.delay()`` call in ``create_agent_run`` — if that message never
    reaches a worker (broker outage at that exact moment), the row stays
    ``PENDING`` forever: the RUNNING-only sweep above can never see it, since
    it never reaches RUNNING without a worker claiming it first. Re-publishing
    is exactly as safe as the first publish: ``claim_agent_run`` only ever
    transitions a row out of PENDING once, under its own row lock, so no
    side effect has happened yet — this never risks duplicating one, unlike
    recovering a RUNNING row.
    """
    pending_cutoff = now - timedelta(seconds=settings.AGENTS_STUCK_RUN_PENDING_STALE_SECONDS)
    run_ids = list(
        AgentRun.objects.filter(status=AgentRunStatus.PENDING, created_at__lte=pending_cutoff)
        .order_by("created_at")
        .values_list("id", flat=True)[:batch_size]
    )
    for run_id in run_ids:
        _redispatch_run(run_id)
    if run_ids:
        logger.info(
            "agents_stuck_pending_run_redispatched",
            extra={"event": "agents_stuck_pending_run_redispatched", "count": len(run_ids)},
        )
        observe_stuck_run_recovery(domain="agent_pending_dispatch", count=len(run_ids))
    return len(run_ids)


def _redispatch_run(run_id) -> None:
    from .services import _dispatch_run

    _dispatch_run(run_id)


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
