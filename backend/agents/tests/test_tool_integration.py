"""End-to-end agent-run + tool-execution integration (Phase 6 acceptance
scenarios A, C, N and the tool-call budget scenario, section 85-88)."""

from __future__ import annotations

import pytest

from agents import services
from agents.models import AgentRunStatus, AgentStepType
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.providers.schemas import ToolCallRequest
from tools.models import ToolExecution, ToolExecutionStatus
from tools.tests.factories import ToolBindingFactory, ToolDefinitionFactory

from .factories import AgentRunFactory, PublishedAgentVersionFactory


def _use_fake_provider(monkeypatch, scenarios):
    provider = DeterministicFakeLLMProvider(scenarios)
    monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
    return provider


@pytest.mark.django_db
class TestFullToolRoundtrip:
    def test_agent_requests_a_bound_tool_and_completes_the_run(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=2, max_tool_calls=3)
        tool_definition = ToolDefinitionFactory(key="demo.echo", handler_key="demo.echo")
        ToolBindingFactory(agent_version=version, tool_definition=tool_definition)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        scenarios = [
            FakeLLMScenario(
                response="",
                tool_calls=(
                    ToolCallRequest(
                        call_id="1", tool_name="demo.echo", arguments={"message": "hi"}
                    ),
                ),
            ),
            FakeLLMScenario(response="Done: hi"),
        ]
        provider = _use_fake_provider(monkeypatch, scenarios)

        result = services.execute_agent_run(run.id)
        replayed = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert replayed.id == result.id
        assert result.final_response == "Done: hi"
        assert provider.call_count == 2
        assert result.tool_call_count == 1

        execution = ToolExecution.objects.get(agent_run=run)
        assert execution.status == ToolExecutionStatus.SUCCEEDED
        assert execution.result_redacted == {"echoed": "hi"}

        step_types = list(result.steps.order_by("sequence").values_list("step_type", flat=True))
        assert AgentStepType.TOOL_REQUESTED in step_types
        assert AgentStepType.TOOL_EXECUTION_STARTED in step_types
        assert AgentStepType.TOOL_EXECUTION_SUCCEEDED in step_types


@pytest.mark.django_db
class TestToolFailureAgentIntegration:
    def test_failing_tool_is_safely_reported_for_a_follow_up(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=2, max_tool_calls=3)
        tool_definition = ToolDefinitionFactory(key="demo.flaky", handler_key="demo.flaky")
        ToolBindingFactory(agent_version=version, tool_definition=tool_definition)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        scenarios = [
            FakeLLMScenario(
                response="",
                tool_calls=(
                    ToolCallRequest(
                        call_id="1", tool_name="demo.flaky", arguments={"fail_attempts": 5}
                    ),
                ),
            ),
            FakeLLMScenario(response="I could not complete that action."),
        ]
        provider = _use_fake_provider(monkeypatch, scenarios)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert result.final_response == "I could not complete that action."
        assert "tool_retry_exhausted" in _useful_request_text(provider.requests[1])

        execution = ToolExecution.objects.get(agent_run=run)
        assert execution.status == ToolExecutionStatus.FAILED

        step_types = list(result.steps.order_by("sequence").values_list("step_type", flat=True))
        assert AgentStepType.TOOL_EXECUTION_FAILED in step_types

        for step in result.steps.all():
            assert "Traceback" not in str(step.safe_metadata)


@pytest.mark.django_db
class TestUnknownToolAgentIntegration:
    def test_unregistered_tool_request_fails_safely(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=2, max_tool_calls=3)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        scenarios = [
            FakeLLMScenario(
                response="",
                tool_calls=(ToolCallRequest(call_id="1", tool_name="system.shell", arguments={}),),
            ),
            FakeLLMScenario(response="That tool is unavailable."),
        ]
        provider = _use_fake_provider(monkeypatch, scenarios)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert "tool_not_registered" in _useful_request_text(provider.requests[1])
        assert not ToolExecution.objects.filter(agent_run=run).exists()


@pytest.mark.django_db
class TestUnboundToolAgentIntegration:
    def test_registered_but_unbound_tool_request_fails_safely(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=2, max_tool_calls=3)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        scenarios = [
            FakeLLMScenario(
                response="",
                tool_calls=(
                    ToolCallRequest(call_id="1", tool_name="demo.add", arguments={"a": 1, "b": 2}),
                ),
            ),
            FakeLLMScenario(response="That action is unavailable."),
        ]
        provider = _use_fake_provider(monkeypatch, scenarios)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert "tool_not_bound" in _useful_request_text(provider.requests[1])


@pytest.mark.django_db
class TestToolCallBudgetAgentIntegration:
    def test_second_tool_request_in_the_same_turn_is_ignored_not_queued(self, monkeypatch):
        """Only the first tool call proposed in one model turn is honored
        (section 43) — this alone keeps a single turn bounded regardless of
        how many calls a provider proposes at once."""
        version = PublishedAgentVersionFactory(max_model_calls=2, max_tool_calls=1)
        tool_definition = ToolDefinitionFactory(key="demo.echo", handler_key="demo.echo")
        ToolBindingFactory(agent_version=version, tool_definition=tool_definition)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        scenarios = [
            FakeLLMScenario(
                response="",
                tool_calls=(
                    ToolCallRequest(call_id="1", tool_name="demo.echo", arguments={"message": "a"}),
                    ToolCallRequest(call_id="2", tool_name="demo.echo", arguments={"message": "b"}),
                ),
            ),
            FakeLLMScenario(response="ok"),
        ]
        _use_fake_provider(monkeypatch, scenarios)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert ToolExecution.objects.filter(agent_run=run).count() == 1

    def test_tool_call_budget_blocks_a_second_round_trip(self, monkeypatch):
        version = PublishedAgentVersionFactory(max_model_calls=5, max_tool_calls=1, max_steps=50)
        tool_definition = ToolDefinitionFactory(key="demo.echo", handler_key="demo.echo")
        ToolBindingFactory(agent_version=version, tool_definition=tool_definition)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        tool_call_scenario = FakeLLMScenario(
            response="",
            tool_calls=(
                ToolCallRequest(call_id="1", tool_name="demo.echo", arguments={"message": "a"}),
            ),
        )
        # Every provider turn proposes another tool call; only the first is
        # ever actually executed because max_tool_calls=1.
        _use_fake_provider(monkeypatch, [tool_call_scenario])

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.BUDGET_EXCEEDED
        assert result.failure_code == "budget_exceeded:max_tool_calls_reached"
        assert ToolExecution.objects.filter(agent_run=run).count() == 1


def _useful_request_text(request):
    return "\n".join(message.content for message in request.messages)
