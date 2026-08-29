"""Unit tests for the domain metric recorders themselves (Phase 11 Block 3)
— bounded-label-collapse behavior and observation branches, mirroring
``observability/tests/test_metrics.py``'s style for Block 1's HTTP/Celery
metrics."""

from __future__ import annotations

from observability.metrics import (
    METRIC_NAMESPACE,
    observe_agent_run_terminal,
    observe_approval_decision,
    observe_approval_request_created,
    observe_handoff_created,
    observe_handoff_terminal,
    observe_llm_request,
    observe_policy_decision,
    observe_tool_execution,
    render_metrics,
)


def _sample_value(*, metric_name: str, labels: dict) -> float | None:
    from prometheus_client.parser import text_string_to_metric_families

    body = render_metrics().decode("utf-8")
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return None


class TestAgentRunMetric:
    def test_unbounded_trigger_collapses_to_manual(self):
        observe_agent_run_terminal(
            trigger="attacker-supplied-trigger", outcome="succeeded", duration_seconds=1.0
        )
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_agent_runs_total",
            labels={"trigger": "manual", "outcome": "succeeded"},
        )
        assert value is not None and value >= 1

    def test_unbounded_outcome_collapses_to_failed(self):
        observe_agent_run_terminal(
            trigger="api", outcome="something-unbounded", duration_seconds=1.0
        )
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_agent_runs_total",
            labels={"trigger": "api", "outcome": "failed"},
        )
        assert value is not None and value >= 1

    def test_none_duration_skips_the_histogram_without_raising(self):
        observe_agent_run_terminal(trigger="manual", outcome="cancelled", duration_seconds=None)


class TestLlmMetric:
    def test_unbounded_provider_collapses_to_other(self):
        observe_llm_request(provider="attacker-provider", outcome="success", duration_seconds=0.1)
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_llm_requests_total",
            labels={"provider": "other", "outcome": "success"},
        )
        assert value is not None and value >= 1

    def test_unbounded_outcome_collapses_to_provider_unknown_error(self):
        observe_llm_request(provider="fake", outcome="not-a-real-code", duration_seconds=0.1)
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_llm_requests_total",
            labels={"provider": "fake", "outcome": "provider_unknown_error"},
        )
        assert value is not None and value >= 1

    def test_token_counts_observed_only_when_provided(self):
        observe_llm_request(
            provider="fake",
            outcome="success",
            duration_seconds=0.1,
            input_tokens=10,
            output_tokens=5,
        )
        input_value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_llm_tokens_total",
            labels={"provider": "fake", "token_type": "input"},
        )
        output_value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_llm_tokens_total",
            labels={"provider": "fake", "token_type": "output"},
        )
        assert input_value is not None and input_value >= 10
        assert output_value is not None and output_value >= 5


class TestToolExecutionMetric:
    def test_unbounded_outcome_collapses_to_failed(self):
        observe_tool_execution(tool_name="demo.tool", outcome="not-real", duration_seconds=0.1)
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_tool_executions_total",
            labels={"tool_name": "demo.tool", "outcome": "failed"},
        )
        assert value is not None and value >= 1

    def test_empty_tool_name_collapses_to_unknown(self):
        observe_tool_execution(tool_name="", outcome="succeeded", duration_seconds=0.1)
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_tool_executions_total",
            labels={"tool_name": "unknown", "outcome": "succeeded"},
        )
        assert value is not None and value >= 1


class TestPolicyDecisionMetric:
    def test_unbounded_decision_collapses_to_deny(self):
        observe_policy_decision(decision="not-a-real-decision")
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_policy_decisions_total", labels={"decision": "deny"}
        )
        assert value is not None and value >= 1


class TestApprovalMetrics:
    def test_created_counter_increments(self):
        before = _sample_value(metric_name=f"{METRIC_NAMESPACE}_approval_requests_total", labels={})
        observe_approval_request_created()
        after = _sample_value(metric_name=f"{METRIC_NAMESPACE}_approval_requests_total", labels={})
        assert (after or 0) > (before or 0)

    def test_unbounded_outcome_collapses_to_expired(self):
        observe_approval_decision(outcome="not-real", wait_duration_seconds=1.0)
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_approval_decisions_total",
            labels={"outcome": "expired"},
        )
        assert value is not None and value >= 1


class TestHandoffMetrics:
    def test_unbounded_reason_code_collapses_to_policy_escalation(self):
        observe_handoff_created(reason_code="not-a-real-reason")
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_handoffs_total",
            labels={"reason_code": "policy_escalation"},
        )
        assert value is not None and value >= 1

    def test_terminal_with_duration_observes_the_histogram(self):
        observe_handoff_terminal(duration_seconds=42.0)
        body = render_metrics().decode("utf-8")
        assert f"{METRIC_NAMESPACE}_handoff_duration_seconds" in body

    def test_terminal_with_none_duration_is_a_safe_no_op(self):
        observe_handoff_terminal(duration_seconds=None)  # must not raise
