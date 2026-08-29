"""Domain observability hard gates (Phase 11 Block 3, sections 32-35, 41,
47-50): cardinality, secret isolation, failure isolation, no double
counting, and trace lineage — exercised through the real domain services
with deterministic fakes, never a live provider.

``transaction=True`` is required throughout: every domain metric here is
recorded via ``transaction.on_commit`` (section 36-37), which never fires
inside the ordinary rolled-back test transaction ``@pytest.mark.django_db``
otherwise wraps each test in.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from prometheus_client.parser import text_string_to_metric_families

from accounts.tests.factories import UserFactory
from agents import orchestration, services
from agents.providers.errors import ProviderTimeoutError
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.tests.factories import PublishedAgentVersionFactory
from approvals.models import ApprovalDecisionValue
from approvals.services import decide_approval
from approvals.tests.factories import pending_refund_approval
from conversations.tests.factories import ConversationFactory, MessageFactory
from observability.metrics import METRIC_NAMESPACE, render_metrics
from observability.tracing import domain_span
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

SECRET_MARKER = "SUPER_SECRET_DOMAIN_OBSERVABILITY_793214"


def _use_fake_provider(monkeypatch, scenario):
    provider = DeterministicFakeLLMProvider(scenario)
    monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
    return provider


def _metrics_text() -> str:
    return render_metrics().decode("utf-8")


def _samples(metric_name: str):
    body = _metrics_text()
    return [
        sample
        for family in text_string_to_metric_families(body)
        for sample in family.samples
        if sample.name == metric_name
    ]


@pytest.mark.django_db(transaction=True)
class TestAgentRunOutcomeSemantics:
    def test_succeeded_run_is_recorded_with_the_succeeded_outcome(self, monkeypatch):
        _use_fake_provider(monkeypatch, FakeLLMScenario(response="ok"))
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation, body="hi")
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        run = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=UserFactory(),
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        orchestration.execute_support_agent_run(run.id)

        matching = [
            s
            for s in _samples(f"{METRIC_NAMESPACE}_agent_runs_total")
            if s.labels.get("outcome") == "succeeded" and s.labels.get("trigger") == "conversation"
        ]
        assert matching and matching[0].value >= 1

    def test_waiting_for_approval_is_never_recorded_as_a_terminal_outcome(self, monkeypatch):
        """Hard rule (section 13): WAITING_FOR_APPROVAL must never appear as
        an ``agent_runs_total`` outcome label value."""
        run, approval, _fake = pending_refund_approval(monkeypatch)

        body = _metrics_text()
        for family in text_string_to_metric_families(body):
            for sample in family.samples:
                if sample.name == f"{METRIC_NAMESPACE}_agent_runs_total":
                    assert sample.labels.get("outcome") != "waiting_for_approval"


@pytest.mark.django_db(transaction=True)
class TestCardinalityAttack:
    def test_many_distinct_runs_never_create_unbounded_label_values(self, monkeypatch):
        """Section 32: many distinct workspace/agent-run/conversation/trace
        ids must never create independent label values/time series — only
        the bounded outcome/trigger taxonomy may vary. Prometheus counters
        are process-global (not reset between tests), so this asserts the
        actual security property — none of *this test's own* generated ids
        leak into the metrics text, and the total (trigger, outcome)
        label-value combination count stays within the small bounded
        universe (4 triggers x 5 outcomes = 20 at most) — never asserts an
        exact singleton set, which would be fragile against whatever other
        tests already ran in this process."""
        run_ids = []
        for _ in range(15):
            _use_fake_provider(monkeypatch, FakeLLMScenario(response="ok"))
            conversation = ConversationFactory()
            message = MessageFactory(conversation=conversation, body="hi")
            version = PublishedAgentVersionFactory(
                agent_definition__workspace=conversation.workspace
            )
            run = orchestration.start_support_agent_run(
                workspace=conversation.workspace,
                actor=UserFactory(),
                conversation=conversation,
                trigger_message=message,
                agent_version=version,
            )
            orchestration.execute_support_agent_run(run.id)
            run_ids.append(str(run.id))
            run_ids.append(str(conversation.id))
            run_ids.append(str(conversation.workspace_id))

        body = _metrics_text()
        for leaked_id in run_ids:
            assert leaked_id not in body

        agent_run_label_sets = {
            frozenset(s.labels.items())
            for family in text_string_to_metric_families(body)
            for s in family.samples
            if s.name == f"{METRIC_NAMESPACE}_agent_runs_total"
        }
        # 4 triggers x 5 outcomes is the entire possible universe — 15
        # distinct AgentRun/conversation/workspace ids (plus whatever any
        # other test in this process already recorded) never exceed it.
        assert len(agent_run_label_sets) <= 20
        assert (
            frozenset({"trigger": "conversation", "outcome": "succeeded"}.items())
            in agent_run_label_sets
        )

    def test_many_distinct_tool_executions_stay_one_bounded_series(self, monkeypatch):
        """Section 32: 10 distinct ToolExecution/ApprovalRequest ids never
        leak into the metrics text, and the specific (tool_name=
        "payment.refund", outcome) combinations this test exercises stay a
        small, bounded set — never asserts exclusivity over samples other
        tests in this process may also have recorded for other tools."""
        execution_ids = []
        for _ in range(10):
            _run, approval, _fake = pending_refund_approval(monkeypatch)
            execution_ids.append(str(approval.tool_execution_id))
            execution_ids.append(str(approval.id))

        body = _metrics_text()
        for leaked_id in execution_ids:
            assert leaked_id not in body

        refund_label_sets = {
            frozenset(s.labels.items())
            for family in text_string_to_metric_families(body)
            for s in family.samples
            if s.name == f"{METRIC_NAMESPACE}_tool_executions_total"
            and s.labels.get("tool_name") == "payment.refund"
        }
        # payment.refund x 6 possible outcomes is the entire universe for
        # this tool — 10 distinct executions never exceed it.
        assert len(refund_label_sets) <= 6


@pytest.mark.django_db(transaction=True)
class TestSecretMarkerAttack:
    def test_marker_in_llm_response_never_reaches_metrics_or_logs(self, monkeypatch, caplog):
        import logging

        _use_fake_provider(monkeypatch, FakeLLMScenario(response=SECRET_MARKER))
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation, body="hi")
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        run = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=UserFactory(),
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        with caplog.at_level(logging.DEBUG):
            orchestration.execute_support_agent_run(run.id)

        assert SECRET_MARKER not in _metrics_text()
        for record in caplog.records:
            assert SECRET_MARKER not in record.getMessage()

    def test_marker_in_provider_exception_never_reaches_metrics(self, monkeypatch):
        class SecretTimeout(ProviderTimeoutError):
            def __init__(self):
                super().__init__(SECRET_MARKER)

        _use_fake_provider(monkeypatch, FakeLLMScenario(error=SecretTimeout))
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation, body="hi")
        version = PublishedAgentVersionFactory(
            agent_definition__workspace=conversation.workspace, max_model_calls=1
        )
        run = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=UserFactory(),
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        orchestration.execute_support_agent_run(run.id)

        assert SECRET_MARKER not in _metrics_text()

    def test_marker_in_approval_comment_never_reaches_metrics(self, monkeypatch):
        run, approval, _fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=membership.user,
            actor_role=membership.role,
            decision=ApprovalDecisionValue.REJECT,
            comment=SECRET_MARKER,
        )

        assert SECRET_MARKER not in _metrics_text()

    def test_marker_in_span_data_across_domain_boundaries(self, monkeypatch, traced):
        _use_fake_provider(monkeypatch, FakeLLMScenario(response=SECRET_MARKER))
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation, body=SECRET_MARKER)
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        run = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=UserFactory(),
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        orchestration.execute_support_agent_run(run.id)

        for span in traced.get_finished_spans():
            assert SECRET_MARKER not in span.name
            for value in span.attributes.values():
                assert SECRET_MARKER not in str(value)
            for event in span.events:
                assert SECRET_MARKER not in event.name
                assert SECRET_MARKER not in str(event.attributes)


@pytest.mark.django_db(transaction=True)
class TestFailureIsolation:
    def test_broken_agent_run_metric_recording_does_not_affect_the_run_status(self, monkeypatch):
        import observability.metrics as metrics_module

        def _boom(**kwargs):
            raise RuntimeError("metrics backend exploded")

        monkeypatch.setattr(metrics_module, "observe_agent_run_terminal", _boom)

        _use_fake_provider(monkeypatch, FakeLLMScenario(response="ok"))
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation, body="hi")
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        run = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=UserFactory(),
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        result = orchestration.execute_support_agent_run(run.id)

        from agents.models import AgentRunStatus

        assert result.status == AgentRunStatus.SUCCEEDED

    def test_broken_tool_execution_metric_recording_does_not_affect_execution_status(
        self, monkeypatch
    ):
        import observability.metrics as metrics_module

        monkeypatch.setattr(
            metrics_module,
            "observe_tool_execution",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        run, approval, _fake = pending_refund_approval(monkeypatch)

        from tools.models import ToolExecutionStatus

        assert approval.tool_execution.status == ToolExecutionStatus.WAITING_FOR_APPROVAL

    def test_broken_domain_span_creation_does_not_affect_business_result(self, monkeypatch):
        import observability.tracing as tracing_module

        monkeypatch.setattr(
            tracing_module,
            "get_tracer",
            lambda: (_ for _ in ()).throw(RuntimeError("tracer exploded")),
        )
        settings_enabled = True
        from django.test import override_settings

        with override_settings(OBSERVABILITY_TRACING_ENABLED=settings_enabled):
            _use_fake_provider(monkeypatch, FakeLLMScenario(response="ok"))
            conversation = ConversationFactory()
            message = MessageFactory(conversation=conversation, body="hi")
            version = PublishedAgentVersionFactory(
                agent_definition__workspace=conversation.workspace
            )
            run = orchestration.start_support_agent_run(
                workspace=conversation.workspace,
                actor=UserFactory(),
                conversation=conversation,
                trigger_message=message,
                agent_version=version,
            )
            result = orchestration.execute_support_agent_run(run.id)

        from agents.models import AgentRunStatus

        assert result.status == AgentRunStatus.SUCCEEDED


@pytest.mark.django_db(transaction=True)
class TestNoDoubleCounting:
    def test_reused_idempotent_tool_execution_is_not_double_counted(self, monkeypatch):
        from integrations.models import IntegrationProvider
        from integrations.providers.base import NormalizedPayment
        from integrations.providers.fakes import FakePaymentProvider
        from integrations.tests.factories import (
            IntegrationConnectionFactory,
            bind_tool,
            running_run,
        )
        from tools.execution import execute_tool

        run = running_run()
        bind_tool(run, "payment.refund")
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.STRIPE)
        fake = FakePaymentProvider(
            payments={
                "pi_1": NormalizedPayment(
                    payment_id="pi_1",
                    external_payment_id="pi_1",
                    status="succeeded",
                    amount_minor=100000,
                    currency="USD",
                    created_at=datetime(2024, 1, 1, tzinfo=UTC),
                    refunded_amount_minor=0,
                )
            }
        )
        monkeypatch.setattr("integrations.services.get_payment_provider", lambda provider: fake)
        kwargs = dict(
            agent_run=run,
            tool_key="payment.refund",
            arguments={"payment_reference": "pi_1", "amount_minor": 500, "currency": "usd"},
            idempotency_key="fixed-key",
        )

        execute_tool(**kwargs)
        before = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_tool_executions_total")
            if s.labels.get("outcome") == "succeeded"
            and s.labels.get("tool_name") == "payment.refund"
        )
        execute_tool(**kwargs)  # idempotent replay — reused=True
        after = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_tool_executions_total")
            if s.labels.get("outcome") == "succeeded"
            and s.labels.get("tool_name") == "payment.refund"
        )

        assert after == before

    def test_replayed_approval_decision_is_not_double_counted(self, monkeypatch):
        run, approval, _fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=membership.user,
            actor_role=membership.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        approval.refresh_from_db()
        before = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_approval_decisions_total")
            if s.labels.get("outcome") == "approved"
        )
        # Idempotent replay of the exact same decision (section 42 of the
        # Phase 8 brief) — must not raise and must not double-count.
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=membership.user,
            actor_role=membership.role,
            decision=ApprovalDecisionValue.APPROVE,
        )
        after = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_approval_decisions_total")
            if s.labels.get("outcome") == "approved"
        )

        assert after == before


@pytest.mark.django_db(transaction=True)
class TestTraceLineageEndToEnd:
    def test_agent_run_span_parents_the_llm_span(self, monkeypatch, traced):
        """Section 41: verified via actual captured span parent/trace
        relationships, not merely that spans exist."""
        _use_fake_provider(monkeypatch, FakeLLMScenario(response="ok"))
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation, body="hi")
        version = PublishedAgentVersionFactory(agent_definition__workspace=conversation.workspace)
        run = orchestration.start_support_agent_run(
            workspace=conversation.workspace,
            actor=UserFactory(),
            conversation=conversation,
            trigger_message=message,
            agent_version=version,
        )
        orchestration.execute_support_agent_run(run.id)

        finished = {span.name: span for span in traced.get_finished_spans()}
        assert "agent.run" in finished
        assert "llm.generate" in finished
        agent_span = finished["agent.run"]
        llm_span = finished["llm.generate"]
        assert agent_span.attributes["supportpilot.agent_run_id"] == str(run.id)
        assert llm_span.attributes["llm.provider"] == "fake"
        assert llm_span.parent.span_id == agent_span.context.span_id
        assert llm_span.context.trace_id == agent_span.context.trace_id
        # No prompt/response text on either span — attribute keys are the
        # complete, exhaustive allowlist, not merely "contains the id".
        assert set(agent_span.attributes.keys()) == {
            "supportpilot.agent_run_id",
            "supportpilot.outcome",
        }
        assert set(llm_span.attributes.keys()) == {"llm.provider", "supportpilot.outcome"}

    def test_tool_execute_span_is_created_on_the_approval_resume_path(self, monkeypatch, traced):
        """Section 42: ``tools.execution.resume_after_approval`` — the
        function ``agents.services._continue_run_after_resumed_tool`` calls
        from inside its own fresh ``agent.run.resume`` domain span — still
        produces a real ``tool.execute`` child span once the approved
        handler actually runs, parented under whatever span is current at
        the time (proving the parenting mechanism itself, independent of
        driving the full AgentRun WAITING_FOR_APPROVAL/resume state machine,
        which ``pending_refund_approval`` — a tool-level fixture — does not
        exercise; that state machine itself is covered by
        ``agents/tests/test_orchestration_hardening.py``)."""
        from tools.execution import resume_after_approval

        run, approval, _fake = pending_refund_approval(monkeypatch)
        approver = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=approver.user,
            actor_role=approver.role,
            decision=ApprovalDecisionValue.APPROVE,
        )

        with domain_span("agent.run.resume") as resume_span:
            resume_after_approval(tool_execution_id=str(approval.tool_execution_id))

        finished = {span.name: span for span in traced.get_finished_spans()}
        assert "tool.execute" in finished
        tool_span = finished["tool.execute"]
        assert tool_span.attributes["tool.name"] == "payment.refund"
        # No args/result payload attributes on the tool span.
        assert set(tool_span.attributes.keys()) == {
            "tool.name",
            "supportpilot.tool_execution_id",
            "supportpilot.outcome",
        }
        resume_context = resume_span.get_span_context()
        assert tool_span.parent.span_id == resume_context.span_id
        assert tool_span.context.trace_id == resume_context.trace_id
