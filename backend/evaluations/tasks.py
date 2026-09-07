"""Thin Celery boundary for asynchronous evaluation batch execution.

Task bodies never duplicate domain logic — every idempotency/concurrency
guarantee lives in ``evaluations.services`` (row-level claims under
``select_for_update``), not here (section 22-24 of the Phase 12 brief).
"""

from celery import shared_task

from common.tasks import CorrelatedTask

from .services import (
    claim_evaluation_run,
    dispatch_pending_case_executions,
    execute_evaluation_case,
)


@shared_task(bind=True, base=CorrelatedTask, max_retries=3)
def start_evaluation_run_task(self, run_id: str, correlation_id: str | None = None):
    run = claim_evaluation_run(run_id)
    if run is None:
        return None
    dispatch_pending_case_executions(run)
    return run.status


@shared_task(bind=True, base=CorrelatedTask, max_retries=3)
def execute_evaluation_case_task(self, result_id: str, correlation_id: str | None = None):
    return execute_evaluation_case(result_id).status


@shared_task(bind=True, base=CorrelatedTask, max_retries=0)
def recover_stuck_evaluation_runs_task(self) -> int:
    """Celery Beat wrapper (Phase 17) around ``evaluations.recovery
    .recover_stuck_evaluation_runs`` — carries zero recovery logic of its
    own. Safe to run from more than one Beat scheduler at once (each
    candidate run is only ever recovered once under its own row lock; see
    that module's docstring) and safe to invoke manually/out-of-band."""
    from .recovery import recover_stuck_evaluation_runs

    return recover_stuck_evaluation_runs()
