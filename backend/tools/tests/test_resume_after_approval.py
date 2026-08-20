"""Direct coverage of ``tools.execution.resume_after_approval``'s edge
branches (section 62-63, 67-68): already-resolved replay, hard-safety
re-checks, and resumed-handler failure paths."""

from __future__ import annotations

import pytest

from approvals.models import ApprovalDecisionValue
from approvals.services import decide_approval
from approvals.tests.factories import pending_refund_approval
from tools.errors import (
    ToolApprovalRejectedError,
    ToolDisabledError,
    ToolError,
    ToolInvalidInputError,
)
from tools.execution import resume_after_approval
from tools.models import ToolBinding, ToolExecution, ToolExecutionStatus
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory


def _approve(run, approval):
    approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
    return decide_approval(
        workspace=run.workspace,
        approval_request=approval,
        actor=approver.user,
        actor_role=approver.role,
        decision=ApprovalDecisionValue.APPROVE,
    )


@pytest.mark.django_db(transaction=True)
class TestResumeRaceAndReplay:
    def test_second_resume_call_after_success_replays_the_stored_result(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        _approve(run, approval)
        first = resume_after_approval(tool_execution_id=str(approval.tool_execution_id))
        assert first.reused is False
        second = resume_after_approval(tool_execution_id=str(approval.tool_execution_id))
        assert second.reused is True
        assert second.output == first.output
        assert fake.refund_call_count == 1

    def test_second_resume_call_after_rejection_replays_the_rejection(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.REJECT,
        )
        with pytest.raises(ToolApprovalRejectedError):
            resume_after_approval(tool_execution_id=str(approval.tool_execution_id))
        assert fake.refund_call_count == 0


@pytest.mark.django_db(transaction=True)
class TestResumeHardSafetyChecks:
    def test_tool_disabled_while_waiting_fails_safely_at_resume(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        _approve(run, approval)
        ToolBinding.objects.filter(
            agent_version=run.agent_version, tool_definition__key="payment.refund"
        ).update(enabled=False)
        with pytest.raises(ToolDisabledError):
            resume_after_approval(tool_execution_id=str(approval.tool_execution_id))
        assert fake.refund_call_count == 0
        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.FAILED
        assert execution.error_code == "tool_disabled"

    def test_corrupted_argument_snapshot_fails_closed_not_silently_wrong(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        _approve(run, approval)
        # Simulate a snapshot that can no longer validate against the
        # tool's schema (e.g. a redaction placeholder for a hypothetical
        # future sensitive field) — resume must fail closed, never execute
        # with a substituted/guessed value.
        ToolExecution.objects.filter(pk=approval.tool_execution_id).update(
            arguments_redacted={
                "payment_reference": "pi_1",
                "amount_minor": "***REDACTED***",
                "currency": "usd",
            }
        )
        with pytest.raises(ToolInvalidInputError):
            resume_after_approval(tool_execution_id=str(approval.tool_execution_id))
        assert fake.refund_call_count == 0
        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.FAILED
        assert execution.error_code == "tool_invalid_input"


@pytest.mark.django_db(transaction=True)
class TestResumedHandlerFailure:
    def test_provider_failure_at_resume_time_finalizes_as_failed(self, monkeypatch):
        from integrations.errors import IntegrationAuthenticationFailedError
        from integrations.providers.fakes import FakePaymentProvider

        run, approval, _old_fake = pending_refund_approval(monkeypatch)
        failing_fake = FakePaymentProvider(
            payments=_old_fake._payments,
            refund_errors=[(IntegrationAuthenticationFailedError(), False)],
        )
        monkeypatch.setattr(
            "integrations.services.get_payment_provider", lambda provider: failing_fake
        )
        _approve(run, approval)
        with pytest.raises(ToolError):
            resume_after_approval(tool_execution_id=str(approval.tool_execution_id))
        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.FAILED
        assert failing_fake.refund_call_count == 1
