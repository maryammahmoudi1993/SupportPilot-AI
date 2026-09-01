"""Unit tests for the deterministic scoring framework (section 52)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from agents.models import AgentRunStatus
from agents.tests.factories import AgentRunFactory
from approvals.models import ApprovalStatus
from tools.models import ToolExecutionStatus
from tools.tests.factories import ToolDefinitionFactory, ToolExecutionFactory

from ..models import EvaluationFailureCode
from ..scoring import score_case


def _run(**kwargs):
    started = timezone.now()
    kwargs.setdefault("status", AgentRunStatus.SUCCEEDED)
    kwargs.setdefault("started_at", started)
    kwargs.setdefault("completed_at", started + timezone.timedelta(milliseconds=42))
    kwargs.setdefault("final_response", "Here is your answer.")
    return AgentRunFactory(**kwargs)


@pytest.mark.django_db
class TestForbiddenAndAllowedTools:
    def test_required_tool_present_passes(self):
        run = _run()
        ToolExecutionFactory(
            agent_run=run,
            tool_definition=ToolDefinitionFactory(key="demo.echo"),
            status=ToolExecutionStatus.SUCCEEDED,
        )
        score = score_case(
            agent_run=run,
            expectations={"required_tool_sequence": ["demo.echo"], "allowed_tools": ["demo.echo"]},
        )
        assert score.passed
        assert score.output.tool_selection_correct is True
        assert score.output.required_sequence_compliant is True

    def test_required_tool_absent_fails(self):
        run = _run()
        score = score_case(agent_run=run, expectations={"required_tool_sequence": ["demo.echo"]})
        assert not score.passed
        assert score.output.required_sequence_compliant is False
        assert score.failure_code == EvaluationFailureCode.OUTCOME_MISMATCH

    def test_forbidden_tool_attempted_but_blocked_is_not_a_violation(self):
        run = _run()
        ToolExecutionFactory(
            agent_run=run,
            tool_definition=ToolDefinitionFactory(key="demo.add"),
            status=ToolExecutionStatus.BLOCKED_BY_POLICY,
        )
        score = score_case(agent_run=run, expectations={"forbidden_tools": ["demo.add"]})
        assert score.passed
        assert score.output.forbidden_tool_violation is False
        assert score.output.forbidden_tools_attempted == ["demo.add"]

    def test_forbidden_tool_actually_executed_is_a_safety_violation(self):
        run = _run()
        ToolExecutionFactory(
            agent_run=run,
            tool_definition=ToolDefinitionFactory(key="demo.add"),
            status=ToolExecutionStatus.SUCCEEDED,
        )
        score = score_case(agent_run=run, expectations={"forbidden_tools": ["demo.add"]})
        assert not score.passed
        assert score.output.forbidden_tool_violation is True
        assert score.failure_code == EvaluationFailureCode.FORBIDDEN_TOOL_VIOLATION

    def test_valid_acceptable_sequence_passes(self):
        run = _run()
        ToolExecutionFactory(
            agent_run=run,
            tool_definition=ToolDefinitionFactory(key="demo.add"),
            status=ToolExecutionStatus.SUCCEEDED,
        )
        score = score_case(
            agent_run=run,
            expectations={"acceptable_tool_sequences": [["demo.echo"], ["demo.add"]]},
        )
        assert score.output.required_sequence_compliant is True

    def test_invalid_sequence_fails(self):
        run = _run()
        ToolExecutionFactory(
            agent_run=run,
            tool_definition=ToolDefinitionFactory(key="demo.flaky"),
            status=ToolExecutionStatus.SUCCEEDED,
        )
        score = score_case(
            agent_run=run, expectations={"acceptable_tool_sequences": [["demo.echo"], ["demo.add"]]}
        )
        assert score.output.required_sequence_compliant is False
        assert not score.passed


@pytest.mark.django_db
class TestApprovalCompliance:
    def _approval(self, run, *, status, tool_key="demo.echo"):
        # Build a minimal, real ApprovalRequest chain directly (no factory
        # exists for RiskAssessment/PolicyEvaluation yet) — these tests only
        # need the resulting ApprovalRequest.status.
        from approvals.models import ApprovalRequest
        from policies.models import PolicyEffect, PolicyEvaluation, RiskAssessment
        from tools.contracts import RiskLevel, SideEffectType

        execution = ToolExecutionFactory(
            agent_run=run,
            tool_definition=ToolDefinitionFactory(key=tool_key),
            status=ToolExecutionStatus.WAITING_FOR_APPROVAL,
        )
        risk = RiskAssessment.objects.create(
            workspace=run.workspace,
            tool_execution=execution,
            tool_key=tool_key,
            base_risk=RiskLevel.HIGH,
            effective_risk=RiskLevel.HIGH,
            side_effect_type=SideEffectType.FINANCIAL,
        )
        policy_eval = PolicyEvaluation.objects.create(
            workspace=run.workspace,
            tool_execution=execution,
            risk_assessment=risk,
            decision=PolicyEffect.REQUIRE_APPROVAL,
            decision_code="high_risk_requires_approval",
            safe_reason="High-risk financial action requires approval.",
        )
        approval = ApprovalRequest.objects.create(
            workspace=run.workspace,
            tool_execution=execution,
            policy_evaluation=policy_eval,
            risk_assessment=risk,
            status=status,
            required_role="owner",
            summary="Refund review",
            expires_at=timezone.now() + timezone.timedelta(hours=1),
        )
        return approval

    def test_approval_required_and_honored(self):
        run = _run()
        self._approval(run, status=ApprovalStatus.APPROVED)
        score = score_case(agent_run=run, expectations={"approval_behavior": "approved_path"})
        assert score.output.approval_compliant is True
        assert not score.output.approval_violation

    def test_approval_bypass_is_a_violation(self):
        run = _run()
        # No ApprovalRequest exists at all — the case expected one.
        score = score_case(agent_run=run, expectations={"approval_behavior": "required"})
        assert score.output.approval_violation is True
        assert score.failure_code == EvaluationFailureCode.APPROVAL_VIOLATION

    def test_rejected_path_compliant(self):
        run = _run()
        self._approval(run, status=ApprovalStatus.REJECTED)
        score = score_case(agent_run=run, expectations={"approval_behavior": "rejected_path"})
        assert score.output.approval_compliant is True


@pytest.mark.django_db
class TestHandoffAndOutcome:
    def test_expected_handoff_present(self):
        run = _run(status=AgentRunStatus.HANDED_OFF)
        score = score_case(
            agent_run=run,
            expectations={
                "approval_behavior": "handoff_expected",
                "outcome_assertions": [{"type": "handoff_created"}],
            },
        )
        assert score.output.handoff_occurred is True
        assert score.output.outcome_assertions_failed == 0

    def test_unexpected_handoff_fails_terminal_state_assertion(self):
        run = _run(status=AgentRunStatus.HANDED_OFF)
        score = score_case(
            agent_run=run,
            expectations={
                "outcome_assertions": [{"type": "run_terminal_state_equals", "value": "succeeded"}]
            },
        )
        assert score.output.outcome_assertions_failed == 1
        assert not score.passed

    def test_expected_terminal_state_matches(self):
        run = _run(status=AgentRunStatus.SUCCEEDED)
        score = score_case(
            agent_run=run,
            expectations={
                "outcome_assertions": [{"type": "run_terminal_state_equals", "value": "succeeded"}]
            },
        )
        assert score.passed

    def test_tool_not_executed_assertion(self):
        run = _run()
        score = score_case(
            agent_run=run,
            expectations={
                "outcome_assertions": [{"type": "tool_not_executed", "tool": "demo.add"}]
            },
        )
        assert score.passed


@pytest.mark.django_db
class TestCitations:
    def test_citation_required_and_present_via_output_message(self):
        from conversations.tests.factories import ConversationFactory, MessageFactory

        conversation = ConversationFactory()
        run = _run(workspace=conversation.workspace, conversation=conversation)
        message = MessageFactory(
            workspace=conversation.workspace,
            conversation=conversation,
            metadata={"citations": [{"chunk_id": "abc"}]},
        )
        run.output_message = message
        run.save()
        score = score_case(
            agent_run=run,
            expectations={"outcome_assertions": [{"type": "response_contains_citation"}]},
        )
        assert score.output.citation_present is True
        assert score.passed

    def test_citation_missing_fails(self):
        run = _run()
        score = score_case(
            agent_run=run,
            expectations={"outcome_assertions": [{"type": "response_contains_citation"}]},
        )
        assert score.output.citation_present is False
        assert not score.passed


@pytest.mark.django_db
class TestIntentNotFabricated:
    def test_intent_is_never_fabricated_when_no_runtime_signal_exists(self):
        run = _run()
        score = score_case(agent_run=run, expectations={"expected_intent": "order_status"})
        # The runtime does not classify/persist intent anywhere (section 25:
        # never report a metric the runtime cannot prove) — the scorer must
        # leave it unevaluated rather than guessing correct/incorrect.
        assert score.output.intent_evaluated is False
        assert score.output.intent_correct is None
