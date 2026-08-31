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
