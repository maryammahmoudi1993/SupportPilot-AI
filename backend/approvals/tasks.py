"""Thin Celery boundary for resuming an approved action (section 66, 127).

The task never duplicates lifecycle logic — it only calls
``agents.services.resume_agent_run_after_approval``, which is itself safe to
invoke more than once for the same approval id (the resume claim inside
``tools.execution.resume_after_approval`` makes a second/redelivered call a
no-op, section 67-68, 128).
"""

from __future__ import annotations

from celery import shared_task


@shared_task(bind=True, max_retries=3)
def resume_approved_action_task(self, approval_request_id: str):
    from agents.services import resume_agent_run_after_approval

    return resume_agent_run_after_approval(approval_request_id)


@shared_task
def expire_stale_approvals_task() -> int:
    """Periodic sweep (section 45) — safe to run on any cadence; each
    ``ApprovalRequest`` is only ever transitioned to ``expired`` once."""
    from .services import expire_stale_approvals

    return expire_stale_approvals()
