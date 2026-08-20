"""Celery task boundary tests (section 66, 127-128, 45) — tasks call
services and return their result; no lifecycle logic lives in the task."""

from __future__ import annotations

import pytest

from approvals.models import ApprovalDecisionValue
from approvals.services import decide_approval
from approvals.tasks import expire_stale_approvals_task, resume_approved_action_task
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import pending_refund_approval


@pytest.mark.django_db(transaction=True)
class TestResumeTask:
    def test_task_resumes_the_approved_run(self, monkeypatch):
        # Isolate "does the task correctly proxy to the service" from
        # decide_approval's own transaction.on_commit dispatch — a real
        # Celery consumer (if one happens to be running against this
        # environment's broker) could otherwise race the explicit .apply()
        # call below and resume the action in a separate process that never
        # saw this test's monkeypatched fake provider.
        import approvals.services as approvals_services

        monkeypatch.setattr(approvals_services, "_dispatch_resume", lambda approval_id: None)

        run, approval, fake = pending_refund_approval(monkeypatch)
        # pending_refund_approval calls tools.execution.execute_tool directly
        # (not the agent graph), so the AgentRun itself is never paused into
        # WAITING_FOR_APPROVAL the way agents.services.execute_agent_run
        # normally would — set it explicitly so the resume claim can
        # succeed, mirroring what _pause_run_for_approval does in production.
        from agents.models import AgentRun, AgentRunStatus

        AgentRun.objects.filter(pk=run.pk).update(status=AgentRunStatus.WAITING_FOR_APPROVAL)

        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        assert fake.refund_call_count == 0  # dispatch was suppressed

        result = resume_approved_action_task.apply(args=[str(approval.id)]).get()
        assert result is not None
        assert fake.refund_call_count == 1


@pytest.mark.django_db(transaction=True)
class TestExpireTask:
    def test_task_delegates_to_the_expiry_service(self, monkeypatch):
        from datetime import timedelta

        from django.utils import timezone

        from approvals.models import ApprovalRequest, ApprovalStatus

        run, approval, fake = pending_refund_approval(monkeypatch)
        past = timezone.now() - timedelta(days=1)
        ApprovalRequest.objects.filter(pk=approval.pk).update(
            created_at=past, expires_at=past + timedelta(seconds=1)
        )
        count = expire_stale_approvals_task.apply().result
        assert count == 1
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.EXPIRED
