"""Thin Celery boundary for asynchronous agent-run execution.

The task never duplicates runtime logic: it only calls
``agents.orchestration.execute_support_agent_run`` (itself a thin wrapper
over ``agents.services.execute_agent_run``), which is safe to invoke more
than once for the same run id (see ``claim_agent_run``).
"""

from celery import shared_task

from common.tasks import CorrelatedTask

from .orchestration import execute_support_agent_run


@shared_task(bind=True, base=CorrelatedTask, max_retries=3)
def execute_agent_run_task(self, run_id: str, correlation_id: str | None = None):
    # ``correlation_id`` is never read here — ``CorrelatedTask.__call__``
    # already popped it off before this body ran and used it to bind the
    # current correlation scope (Phase 11 Block 2). It must still be
    # declared here so Celery's argument validation accepts it at dispatch
    # time (``_dispatch_run`` always passes it as a task kwarg).
    return execute_support_agent_run(run_id).status


@shared_task(bind=True, base=CorrelatedTask, max_retries=0)
def recover_stuck_agent_runs_task(self) -> int:
    """Celery Beat wrapper (Phase 17) around ``agents.recovery
    .recover_stuck_agent_runs`` — carries zero recovery logic of its own.
    Safe to run from more than one Beat scheduler at once (each candidate
    row is only ever recovered once under its own row lock; see that
    module's docstring) and safe to invoke manually/out-of-band."""
    from .recovery import recover_stuck_agent_runs

    return recover_stuck_agent_runs()
