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
    ToolExecutionInProgressError,
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

    def test_two_concurrent_resume_calls_invoke_the_handler_exactly_once(self, monkeypatch):
        """Phase 16 Part A, section 8: a redelivered Celery resume task
        racing an in-flight resume for the same approved ``ToolExecution``
        must never invoke the refund handler twice — proven with real
        threads against ``_claim_resume``'s row lock, not a sequential
        double-call."""
        import threading

        import django.db as django_db

        run, approval, fake = pending_refund_approval(monkeypatch)
        _approve(run, approval)

        barrier = threading.Barrier(2)
        results: list[object] = [None, None]
        errors: list[BaseException | None] = [None, None]

        def make_worker(index):
            def worker():
                django_db.close_old_connections()
                barrier.wait()
                try:
                    results[index] = resume_after_approval(
                        tool_execution_id=str(approval.tool_execution_id)
                    )
                except BaseException as exc:  # noqa: BLE001 - captured for assertion
                    errors[index] = exc
                finally:
                    django_db.close_old_connections()

            return worker

        threads = [threading.Thread(target=make_worker(i)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # The handler runs exactly once no matter how the two calls
        # interleave — the load-bearing assertion for this test.
        assert fake.refund_call_count == 1

        # The losing racer observes one of two honest outcomes depending on
        # timing: it either arrives after the winner has already finalized
        # (SUCCEEDED -> a replayed, non-error result) or while the winner is
        # still mid-flight (RUNNING -> ``ToolExecutionInProgressError``).
        # What it must never do is fabricate a rejection/expiry/policy
        # denial that never actually happened — that was the Phase 16
        # regression this test exists to pin (a spurious
        # ``ToolApprovalRejectedError`` previously reached here and, one
        # layer up, incorrectly failed the whole agent run).
        for exc in errors:
            assert exc is None or isinstance(exc, ToolExecutionInProgressError)

        succeeded = [r for r in results if r is not None]
        assert len(succeeded) >= 1
        for r in succeeded:
            assert r.output == succeeded[0].output
        if len(succeeded) == 2:
            # Both observed the result without error: exactly one of them
            # actually ran the handler, the other replayed it.
            assert sorted(r.reused for r in succeeded) == [False, True]

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

    def test_fingerprint_mismatch_against_the_approval_snapshot_fails_closed(self, monkeypatch):
        """Phase 9 Block 4 (section 8-9, 94, 125-126): the frozen action is
        tied to the exact argument fingerprint recorded on the
        ``ApprovalRequest`` at request time. A ``ToolExecution`` row whose
        fingerprint no longer matches — only reachable through direct data
        tampering — is never "repaired"; resume fails closed with zero
        handler/provider calls."""
        from tools.errors import ToolApprovalActionChangedError

        # A non-blank idempotency key is required for a fingerprint to be
        # recorded at all (``arguments_fingerprint`` is blank whenever no
        # idempotency key was supplied) — every real agent-driven tool call
        # always supplies one (``agents/runtime/graph.py``), so this
        # mirrors production, not the no-idempotency-key factory default.
        run, approval, fake = pending_refund_approval(monkeypatch, idempotency_key="turn-1-key")
        _approve(run, approval)
        ToolExecution.objects.filter(pk=approval.tool_execution_id).update(
            arguments_fingerprint="tampered-fingerprint"
        )
        with pytest.raises(ToolApprovalActionChangedError):
            resume_after_approval(tool_execution_id=str(approval.tool_execution_id))
        assert fake.refund_call_count == 0
        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.FAILED
        assert execution.error_code == "approval_action_changed"

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
