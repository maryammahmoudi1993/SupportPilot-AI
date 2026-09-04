"""Approval lifecycle service tests (section 37-50, 90-95, 141-142)."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.db import connections
from django.utils import timezone

from accounts.tests.factories import UserFactory
from approvals import services
from approvals.errors import (
    ApprovalAlreadyResolvedError,
    ApprovalCancelledError,
    ApprovalExpiredError,
    ApprovalPermissionDeniedError,
    ApprovalSelfApprovalForbiddenError,
)
from approvals.models import (
    ApprovalDecision,
    ApprovalDecisionValue,
    ApprovalRequest,
    ApprovalStatus,
)
from tools.models import ToolExecution, ToolExecutionStatus
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import pending_booking_approval, pending_refund_approval


@pytest.mark.django_db(transaction=True)
class TestApprovalCreation:
    def test_exactly_one_approval_request_per_tool_execution(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        assert ApprovalRequest.objects.filter(tool_execution=approval.tool_execution).count() == 1
        assert approval.status == ApprovalStatus.PENDING
        assert approval.required_role  # non-blank

    def test_approval_captures_safe_context_without_credentials(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        assert approval.safe_context["tool_key"] == "payment.refund"
        assert "secret_key" not in str(approval.safe_context)
        assert "sk_test" not in str(approval.safe_context)  # not "sk_" alone: matches "risk_level"

    def test_execution_is_waiting_for_approval_and_provider_never_called(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        execution = approval.tool_execution
        execution.refresh_from_db()
        assert execution.status == ToolExecutionStatus.WAITING_FOR_APPROVAL
        assert fake.refund_call_count == 0


@pytest.mark.django_db(transaction=True)
class TestDecideApproval:
    def test_approve_by_sufficient_role(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        result = services.decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        assert result.status == ApprovalStatus.APPROVED
        assert ApprovalDecision.objects.filter(approval_request=approval).count() == 1

    def test_reject_by_sufficient_role_terminates_execution(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        result = services.decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.REJECT,
        )
        assert result.status == ApprovalStatus.REJECTED
        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.APPROVAL_TERMINATED
        assert execution.error_code == "approval_rejected"
        assert fake.refund_call_count == 0

    def test_insufficient_role_is_permission_denied(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        # required_role for a REQUIRE_APPROVAL refund between thresholds is
        # derived from CRITICAL risk -> owner; support_manager is too low.
        approver = WorkspaceMembershipFactory(
            workspace=run.workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        with pytest.raises(ApprovalPermissionDeniedError):
            services.decide_approval(
                workspace=run.workspace,
                approval_request=approval,
                actor=approver.user,
                actor_role=approver.role,
                decision=ApprovalDecisionValue.APPROVE,
            )
        assert fake.refund_call_count == 0

    def test_self_approval_is_forbidden(self, monkeypatch):
        # requested_by is the AgentRun's creator; give them owner role and
        # try to decide their own request.
        actor = UserFactory()
        run, approval, fake = pending_refund_approval(monkeypatch, created_by=actor)
        membership = WorkspaceMembershipFactory(
            workspace=run.workspace, user=actor, role=WorkspaceRole.OWNER
        )
        with pytest.raises(ApprovalSelfApprovalForbiddenError):
            services.decide_approval(
                workspace=run.workspace,
                approval_request=approval,
                actor=actor,
                actor_role=membership.role,
                decision=ApprovalDecisionValue.APPROVE,
            )

    def test_repeated_identical_approve_is_idempotent(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        first = services.decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        second = services.decide_approval(
            workspace=run.workspace,
            approval_request=first,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        assert second.status == ApprovalStatus.APPROVED
        assert ApprovalDecision.objects.filter(approval_request=approval).count() == 1

    def test_reject_after_approve_is_a_conflict(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        approved = services.decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        with pytest.raises(ApprovalAlreadyResolvedError):
            services.decide_approval(
                workspace=run.workspace,
                approval_request=approved,
                actor=approver.user,
                actor_role=approver.role,
                decision=ApprovalDecisionValue.REJECT,
            )

    def test_decision_after_expiry_fails_safely(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        # Push both created_at and expires_at into the past together — the
        # DB CheckConstraint requires expires_at > created_at, so only
        # moving expires_at into the past (while created_at stays "now")
        # would violate it.
        past = timezone.now() - timedelta(days=1)
        ApprovalRequest.objects.filter(pk=approval.pk).update(
            created_at=past, expires_at=past + timedelta(seconds=1)
        )
        approval.refresh_from_db()
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        with pytest.raises(ApprovalExpiredError):
            services.decide_approval(
                workspace=run.workspace,
                approval_request=approval,
                actor=approver.user,
                actor_role=approver.role,
                decision=ApprovalDecisionValue.APPROVE,
            )
        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.APPROVAL_TERMINATED
        assert execution.error_code == "approval_expired"
        assert fake.refund_call_count == 0

    def test_decision_on_a_row_already_expired_by_someone_else_fails_safely(self, monkeypatch):
        """Phase 16 Part A, section 9 regression: unlike the test above
        (where this call's own ``_expire_if_stale`` performs the expiry),
        here the row was *already* transitioned to EXPIRED by a prior
        caller (a racing decision, or the periodic sweeper) before this
        call ever acquires the lock. Before the ``decide_approval`` fix,
        this fell through the elif chain into the PENDING-only branch and
        recorded a phantom decision — a false "approved" audit event and
        webhook — even though the underlying ToolExecution was already
        terminated by the original expiry."""
        run, approval, fake = pending_refund_approval(monkeypatch)
        past = timezone.now() - timedelta(days=1)
        ApprovalRequest.objects.filter(pk=approval.pk).update(
            created_at=past,
            expires_at=past + timedelta(seconds=1),
            status=ApprovalStatus.EXPIRED,
            resolved_at=timezone.now(),
        )
        approval.refresh_from_db()
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        with pytest.raises(ApprovalExpiredError):
            services.decide_approval(
                workspace=run.workspace,
                approval_request=approval,
                actor=approver.user,
                actor_role=approver.role,
                decision=ApprovalDecisionValue.APPROVE,
            )
        assert ApprovalDecision.objects.filter(approval_request=approval).count() == 0
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.EXPIRED
        assert fake.refund_call_count == 0

    def test_decision_after_cancellation_fails_safely(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        services.cancel_approval_for_execution(execution=approval.tool_execution)
        approval.refresh_from_db()
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        with pytest.raises(ApprovalCancelledError):
            services.decide_approval(
                workspace=run.workspace,
                approval_request=approval,
                actor=approver.user,
                actor_role=approver.role,
                decision=ApprovalDecisionValue.APPROVE,
            )


@pytest.mark.django_db(transaction=True)
class TestApprovalDedupAndCancelNoop:
    def test_create_or_reuse_returns_existing_row_for_same_execution(self, monkeypatch):
        from approvals.services import create_or_reuse_approval_request
        from tools.registry import registry

        run, approval, fake = pending_refund_approval(monkeypatch)
        execution = approval.tool_execution
        again = create_or_reuse_approval_request(
            execution=execution,
            agent_run=run,
            evaluation=approval.policy_evaluation,
            risk_assessment=approval.risk_assessment,
            required_role=approval.required_role,
            ttl_seconds=3600,
            canonical_arguments={},
            tool=registry.get("payment.refund"),
        )
        assert again.pk == approval.pk
        assert ApprovalRequest.objects.filter(tool_execution=execution).count() == 1

    def test_cancel_is_a_noop_when_no_approval_exists(self, monkeypatch):
        from approvals.services import cancel_approval_for_execution
        from customers.tests.factories import CustomerFactory
        from integrations.tests.factories import bind_tool
        from tools.execution import execute_tool

        run, approval, fake = pending_refund_approval(monkeypatch)
        # A plain read-only tool call (ALLOW path) never gets an
        # ApprovalRequest — cancelling it must not error.
        bind_tool(run, "customer.lookup")
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        execute_tool(
            agent_run=run,
            tool_key="customer.lookup",
            arguments={"email": customer.email},
        )
        other_execution = ToolExecution.objects.exclude(pk=approval.tool_execution_id).get(
            tool_definition__key="customer.lookup"
        )
        cancel_approval_for_execution(execution=other_execution)  # no error, no-op

    def test_cancel_is_a_noop_when_already_resolved(self, monkeypatch):
        from approvals.services import cancel_approval_for_execution

        run, approval, fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        services.decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        cancel_approval_for_execution(execution=approval.tool_execution)  # no-op, already approved
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.APPROVED


@pytest.mark.django_db(transaction=True)
class TestExpiryProcessing:
    def test_expire_stale_approvals_sweeps_pending_only(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        # Push both created_at and expires_at into the past together — the
        # DB CheckConstraint requires expires_at > created_at, so only
        # moving expires_at into the past (while created_at stays "now")
        # would violate it.
        past = timezone.now() - timedelta(days=1)
        ApprovalRequest.objects.filter(pk=approval.pk).update(
            created_at=past, expires_at=past + timedelta(seconds=1)
        )
        count = services.expire_stale_approvals()
        assert count == 1
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.EXPIRED

    def test_expire_stale_approvals_is_a_noop_when_nothing_is_stale(self, monkeypatch):
        pending_refund_approval(monkeypatch)
        assert services.expire_stale_approvals() == 0


@pytest.mark.django_db(transaction=True)
class TestConcurrency:
    def test_two_concurrent_approves_produce_exactly_one_decision(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)

        results = []
        errors = []

        def _decide():
            try:
                results.append(
                    services.decide_approval(
                        workspace=run.workspace,
                        approval_request=ApprovalRequest.objects.get(pk=approval.pk),
                        actor=approver.user,
                        actor_role=approver.role,
                        decision=ApprovalDecisionValue.APPROVE,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - captured for assertion
                errors.append(exc)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=_decide) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert ApprovalDecision.objects.filter(approval_request=approval).count() == 1
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.APPROVED

    def test_approve_vs_reject_race_produces_one_final_status(self, monkeypatch):
        # payment.refund requires "owner" (only one active owner per
        # workspace is allowed), so this race uses two independent admins
        # instead — both satisfy a lower required_role, and multiple admins
        # per workspace are unconstrained.
        run, approval, fake, _arguments = pending_booking_approval(monkeypatch)
        owner1 = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.ADMIN)
        owner2 = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.ADMIN)

        outcomes = []

        def _approve():
            try:
                services.decide_approval(
                    workspace=run.workspace,
                    approval_request=ApprovalRequest.objects.get(pk=approval.pk),
                    actor=owner1.user,
                    actor_role=owner1.role,
                    decision=ApprovalDecisionValue.APPROVE,
                )
                outcomes.append("approve_ok")
            except Exception:  # noqa: BLE001
                outcomes.append("approve_failed")
            finally:
                connections.close_all()

        def _reject():
            try:
                services.decide_approval(
                    workspace=run.workspace,
                    approval_request=ApprovalRequest.objects.get(pk=approval.pk),
                    actor=owner2.user,
                    actor_role=owner2.role,
                    decision=ApprovalDecisionValue.REJECT,
                )
                outcomes.append("reject_ok")
            except Exception:  # noqa: BLE001
                outcomes.append("reject_failed")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=_approve), threading.Thread(target=_reject)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert ApprovalDecision.objects.filter(approval_request=approval).count() == 1
        approval.refresh_from_db()
        assert approval.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)
        # Exactly one side "won" and the other was rejected as a conflict.
        assert outcomes.count("approve_failed") + outcomes.count("reject_failed") == 1

    def _race_decide_against_sweep(self, monkeypatch, *, decision):
        """Shared setup for approve/expire and expire/reject (Phase 16 Part
        A, section 9): a request already past ``expires_at`` racing a human
        decision against the periodic sweeper. Exactly one authoritative
        terminal status must result, never both a decision row and an
        expiry, and never an unresolved PENDING row left behind."""
        run, approval, fake = pending_refund_approval(monkeypatch)
        past = timezone.now() - timedelta(days=1)
        ApprovalRequest.objects.filter(pk=approval.pk).update(
            created_at=past, expires_at=past + timedelta(seconds=1)
        )
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)

        outcomes: list[str] = []

        def _decide():
            try:
                services.decide_approval(
                    workspace=run.workspace,
                    approval_request=ApprovalRequest.objects.get(pk=approval.pk),
                    actor=approver.user,
                    actor_role=approver.role,
                    decision=decision,
                )
                outcomes.append("decide_ok")
            except ApprovalExpiredError:
                outcomes.append("decide_expired")
            except Exception:  # noqa: BLE001
                outcomes.append("decide_failed")
            finally:
                connections.close_all()

        def _sweep():
            try:
                services.expire_stale_approvals()
            finally:
                connections.close_all()

        threads = [threading.Thread(target=_decide), threading.Thread(target=_sweep)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        approval.refresh_from_db()
        # Exactly one ApprovalDecision row may exist (only the "decide" side
        # ever creates one; the sweeper never does), and the final status is
        # always terminal — never a resurrected PENDING.
        assert ApprovalDecision.objects.filter(approval_request=approval).count() <= 1
        return approval, outcomes

    def test_approve_vs_expire_race_produces_one_authoritative_terminal_status(self, monkeypatch):
        approval, outcomes = self._race_decide_against_sweep(
            monkeypatch, decision=ApprovalDecisionValue.APPROVE
        )
        # The sweeper's expiry check runs first inside decide_approval too
        # (_expire_if_stale), so whichever side's transaction commits first
        # wins; the request is always past its deadline here, so EXPIRED is
        # the only state that can ever win — APPROVED must never win a race
        # against an already-expired deadline.
        assert approval.status == ApprovalStatus.EXPIRED
        assert "decide_expired" in outcomes or "decide_ok" not in outcomes

    def test_expire_vs_reject_race_produces_one_authoritative_terminal_status(self, monkeypatch):
        approval, outcomes = self._race_decide_against_sweep(
            monkeypatch, decision=ApprovalDecisionValue.REJECT
        )
        assert approval.status == ApprovalStatus.EXPIRED
        assert "decide_expired" in outcomes or "decide_ok" not in outcomes

    def test_two_concurrent_resumes_invoke_the_continuation_exactly_once(self, monkeypatch):
        """resume/resume (Phase 16 Part A, section 9): two concurrent (e.g.
        redelivered) calls to the real production resume entrypoint for the
        same approval must invoke the refund handler exactly once — proven
        through ``agents.services.resume_agent_run_after_approval`` itself,
        not a lower-layer proxy, so this exercises the full run-level claim
        that gates every resume in production."""
        from agents.models import AgentRun, AgentRunStatus
        from agents.services import resume_agent_run_after_approval

        run, approval, fake = pending_refund_approval(monkeypatch)
        # ``pending_refund_approval`` drives the tool-execution/approval gate
        # directly, not the full orchestration graph, so it leaves the
        # AgentRun itself at RUNNING even though the ToolExecution is
        # WAITING_FOR_APPROVAL. Mirror what the orchestration graph would
        # have done (see agents/services.py::_pause_run_for_approval) so
        # ``_claim_run_for_resume`` has a real WAITING_FOR_APPROVAL row to
        # race over, matching production.
        AgentRun.objects.filter(pk=run.pk).update(status=AgentRunStatus.WAITING_FOR_APPROVAL)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        services.decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )

        results: list[str] = []

        def _resume():
            try:
                results.append(resume_agent_run_after_approval(approval.pk))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=_resume) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert fake.refund_call_count == 1
        assert len(results) == 2
        # Exactly one caller performed the real continuation (the run's
        # terminal/next status); the other observed the run-level claim's
        # own no-op signal.
        assert "already_resumed" in results
        assert any(r != "already_resumed" for r in results)
