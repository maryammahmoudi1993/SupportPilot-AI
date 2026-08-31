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
