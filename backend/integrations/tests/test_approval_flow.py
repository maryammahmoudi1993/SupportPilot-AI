"""End-to-end policy-gated business-tool flows (Phase 8 sections 105-110,
153-158): refund/booking approve, reject, argument-change protection, and
run-level pause/resume/budget preservation.

Drives the *real* agent-run pipeline (``agents.services.execute_agent_run``)
with a scripted deterministic LLM provider — not a direct ``execute_tool``
call — so the run-level pause (``AgentRunStatus.WAITING_FOR_APPROVAL``) and
resume (``agents.services.resume_agent_run_after_approval``) are exercised
for real, exactly as production traffic would hit them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from agents import services as agent_services
from agents.models import AgentRunStatus
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.providers.schemas import ToolCallRequest
from agents.tests.factories import AgentRunFactory, PublishedAgentVersionFactory
from approvals.models import ApprovalDecisionValue, ApprovalRequest, ApprovalStatus
from approvals.services import decide_approval
from customers.tests.factories import CustomerFactory
from integrations.models import IntegrationProvider
from integrations.providers.base import NormalizedPayment
from integrations.providers.fakes import FakeCalendarProvider, FakePaymentProvider
from tools.models import ToolExecution, ToolExecutionStatus
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import IntegrationConnectionFactory, bind_tool


def _payment(**overrides):
    defaults = dict(
        payment_id="pi_1",
        external_payment_id="pi_1",
        status="succeeded",
        amount_minor=100000,
        currency="USD",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        refunded_amount_minor=0,
    )
    defaults.update(overrides)
    return NormalizedPayment(**defaults)


def _use_fake_provider(monkeypatch, scenarios):
    provider = DeterministicFakeLLMProvider(scenarios)
    monkeypatch.setattr(agent_services, "get_llm_provider", lambda: provider)
    return provider


@pytest.mark.django_db(transaction=True)
class TestRefundApprovalEndToEnd:
    def _setup(self, monkeypatch, *, amount_minor=10000):
        version = PublishedAgentVersionFactory(max_model_calls=3, max_tool_calls=3)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)
        bind_tool(run, "payment.refund")
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)

        _use_fake_provider(
            monkeypatch,
            [
                FakeLLMScenario(
                    response="",
                    tool_calls=(
                        ToolCallRequest(
                            call_id="1",
                            tool_name="payment.refund",
                            arguments={
                                "payment_reference": "pi_1",
                                "amount_minor": amount_minor,
                                "currency": "usd",
                            },
                        ),
                    ),
                ),
                FakeLLMScenario(response="Your refund has been processed."),
            ],
        )
        result = agent_services.execute_agent_run(run.id)
        assert result.status == AgentRunStatus.WAITING_FOR_APPROVAL
        approval = ApprovalRequest.objects.get(tool_execution__agent_run=run)
        return result, approval, fake

    def test_approve_resumes_and_calls_provider_exactly_once(self, monkeypatch):
        run, approval, fake = self._setup(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        assert fake.refund_call_count == 0  # not yet — resume dispatch is async via on_commit

        agent_services.resume_agent_run_after_approval(str(approval.id))
        assert fake.refund_call_count == 1

        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.SUCCEEDED
        run.refresh_from_db()
        assert run.status == AgentRunStatus.SUCCEEDED
        assert run.final_response == "Your refund has been processed."

    def test_reject_never_calls_provider(self, monkeypatch):
        run, approval, fake = self._setup(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.REJECT,
        )
        assert fake.refund_call_count == 0
        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.APPROVAL_TERMINATED
        run.refresh_from_db()
        # Rejection terminates the underlying execution but does not itself
        # auto-resume the run (section 70) — no advanced recovery planning
        # in Phase 8.
        assert run.status == AgentRunStatus.WAITING_FOR_APPROVAL

    def test_duplicate_approve_clicks_cause_exactly_one_provider_refund(self, monkeypatch):
        """Section 67-68, 107: two "concurrent" approve-resume deliveries
        (e.g. a duplicate Celery task) -> one resume claim -> one external
        side effect."""
        run, approval, fake = self._setup(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        first = agent_services.resume_agent_run_after_approval(str(approval.id))
        second = agent_services.resume_agent_run_after_approval(str(approval.id))
        assert fake.refund_call_count == 1
        assert first == AgentRunStatus.SUCCEEDED
        assert second == "already_resumed"

    def test_budget_counters_are_not_reset_by_the_pause(self, monkeypatch):
        run, approval, fake = self._setup(monkeypatch)
        pre_model_calls = run.model_call_count
        pre_tool_calls = run.tool_call_count
        assert pre_model_calls >= 1  # the model call that proposed the refund
        assert pre_tool_calls == 0  # the gated tool call never ran yet

        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        agent_services.resume_agent_run_after_approval(str(approval.id))
        run.refresh_from_db()
        # tool_call_count strictly increases by exactly one (the resumed
        # call); model_call_count only ever grows (section 153-155) — the
        # follow-up model turn after resume adds to it, never resets it.
        assert run.tool_call_count == pre_tool_calls + 1
        assert run.model_call_count > pre_model_calls


@pytest.mark.django_db(transaction=True)
class TestBookingApprovalEndToEnd:
    def _setup(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=3, max_tool_calls=3)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)
        bind_tool(run, "calendar.create_booking")
        IntegrationConnectionFactory(
            workspace=run.workspace, provider=IntegrationProvider.GOOGLE_CALENDAR
        )
        fake = FakeCalendarProvider()
        monkeypatch.setattr("integrations.services.get_calendar_provider", lambda provider: fake)
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        start = timezone.now() + timedelta(hours=2)
        end = start + timedelta(minutes=30)
        arguments = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "title": "Onboarding call",
            "customer_id": str(customer.id),
        }
        _use_fake_provider(
            monkeypatch,
            [
                FakeLLMScenario(
                    response="",
                    tool_calls=(
                        ToolCallRequest(
                            call_id="1", tool_name="calendar.create_booking", arguments=arguments
                        ),
                    ),
                ),
                FakeLLMScenario(response="You're booked."),
            ],
        )
        result = agent_services.execute_agent_run(run.id)
        assert result.status == AgentRunStatus.WAITING_FOR_APPROVAL
        approval = ApprovalRequest.objects.get(tool_execution__agent_run=run)
        return result, approval, fake, arguments

    def test_no_booking_created_before_approval(self, monkeypatch):
        run, approval, fake, arguments = self._setup(monkeypatch)
        assert fake.create_booking_call_count == 0

    def test_approve_creates_exactly_one_booking(self, monkeypatch):
        run, approval, fake, arguments = self._setup(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.ADMIN)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        agent_services.resume_agent_run_after_approval(str(approval.id))
        assert fake.create_booking_call_count == 1

    def test_reject_creates_no_booking(self, monkeypatch):
        run, approval, fake, arguments = self._setup(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.ADMIN)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.REJECT,
        )
        assert fake.create_booking_call_count == 0

    def test_resume_uses_the_frozen_snapshot_not_a_changed_argument(self, monkeypatch):
        """Section 54-55, 110: the resumed action always executes the
        exact, stored redacted snapshot — there is no code path at resume
        time that accepts a fresh, caller-supplied argument at all."""
        run, approval, fake, arguments = self._setup(monkeypatch)
        execution = approval.tool_execution
        original_start = execution.arguments_redacted["start"]

        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.ADMIN)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        agent_services.resume_agent_run_after_approval(str(approval.id))

        assert fake.create_booking_call_count == 1
        booking = next(iter(fake._bookings_by_key.values()))
        from datetime import datetime as dt

        assert dt.fromisoformat(original_start) == booking.start


@pytest.mark.django_db(transaction=True)
class TestRunCancellationCancelsApproval:
    def test_cancelling_the_run_cancels_the_pending_approval(self, monkeypatch):
        from agents.services import cancel_agent_run
        from approvals.errors import ApprovalError

        version = PublishedAgentVersionFactory(max_model_calls=3, max_tool_calls=3)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)
        bind_tool(run, "payment.refund")
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
        fake = FakePaymentProvider(payments={"pi_1": _payment()})
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
        _use_fake_provider(
            monkeypatch,
            [
                FakeLLMScenario(
                    response="",
                    tool_calls=(
                        ToolCallRequest(
                            call_id="1",
                            tool_name="payment.refund",
                            arguments={
                                "payment_reference": "pi_1",
                                "amount_minor": 10000,
                                "currency": "usd",
                            },
                        ),
                    ),
                ),
            ],
        )
        result = agent_services.execute_agent_run(run.id)
        assert result.status == AgentRunStatus.WAITING_FOR_APPROVAL
        approval = ApprovalRequest.objects.get(tool_execution__agent_run=result)
        actor = WorkspaceMembershipFactory(workspace=result.workspace, role=WorkspaceRole.OWNER)

        cancel_agent_run(workspace=result.workspace, run=result, actor=actor.user)

        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.CANCELLED
        execution = ToolExecution.objects.get(pk=approval.tool_execution_id)
        assert execution.status == ToolExecutionStatus.CANCELLED

        with pytest.raises(ApprovalError):
            decide_approval(
                workspace=result.workspace,
                approval_request=approval,
                actor=actor.user,
                actor_role=actor.role,
                decision=ApprovalDecisionValue.APPROVE,
            )
        assert fake.refund_call_count == 0
