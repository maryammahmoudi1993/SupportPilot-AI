"""Thin Celery boundary for asynchronous agent-run execution.

The task never duplicates runtime logic: it only calls
``agents.orchestration.execute_support_agent_run`` (itself a thin wrapper
over ``agents.services.execute_agent_run``), which is safe to invoke more
than once for the same run id (see ``claim_agent_run``).
"""

from celery import shared_task

from .orchestration import execute_support_agent_run


@shared_task(bind=True, max_retries=3)
def execute_agent_run_task(self, run_id: str):
    return execute_support_agent_run(run_id).status
