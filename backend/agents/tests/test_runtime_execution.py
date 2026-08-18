"""End-to-end agent-run execution through ``services.execute_agent_run``,
covering the Phase 5 acceptance scenarios A-G."""

from __future__ import annotations

import pytest

from agents import services
from agents.models import AgentRunStatus, AgentStepType
from agents.providers.errors import (
    ProviderAuthenticationError,
    ProviderTimeoutError,
)
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario

from .factories import AgentRunFactory, PublishedAgentVersionFactory


def _use_fake_provider(monkeypatch, scenario):
    provider = DeterministicFakeLLMProvider(scenario)
    monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
    return provider


@pytest.mark.django_db
class TestScenarioASuccessfulRun:
    def test_deterministic_successful_run(self, monkeypatch):
        provider = _use_fake_provider(
            monkeypatch, FakeLLMScenario(response="You can reset your password from Settings.")
        )
        run = AgentRunFactory(input_message="How do I reset my password?")

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.SUCCEEDED
        assert result.final_response == "You can reset your password from Settings."
        assert result.model_call_count == 1
        assert provider.call_count == 1
        assert result.total_tokens == 15
        assert result.started_at is not None
        assert result.completed_at is not None

        step_types = list(result.steps.order_by("sequence").values_list("step_type", flat=True))
        assert step_types == [
            AgentStepType.RUN_STARTED,
            AgentStepType.BUDGET_CHECKED,
            AgentStepType.PROVIDER_CALL_STARTED,
            AgentStepType.PROVIDER_CALL_SUCCEEDED,
            AgentStepType.RESPONSE_FINALIZED,
        ]

    def test_determinism_same_scenario_same_input_same_observable_result(self, monkeypatch):
        def run_once():
            provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="stable answer"))
            monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
            run = AgentRunFactory(input_message="same question")
            result = services.execute_agent_run(run.id)
            return result.final_response, result.status, result.total_tokens

        first = run_once()
        second = run_once()
        assert first == second


@pytest.mark.django_db
class TestScenarioBProviderTimeout:
    def test_retryable_timeout_eventually_fails_safely_when_budget_exhausted(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(error=ProviderTimeoutError))
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        version = PublishedAgentVersionFactory(max_model_calls=3, max_retry_attempts=3)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.FAILED
        assert result.failure_code == "provider_timeout"
        assert provider.call_count == 3  # bounded: never exceeds max_model_calls
        assert result.model_call_count == 3

    def test_retry_never_exceeds_configured_call_budget(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(error=ProviderTimeoutError))
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        version = PublishedAgentVersionFactory(max_model_calls=2, max_retry_attempts=10)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        result = services.execute_agent_run(run.id)

        assert provider.call_count == 2
        assert result.model_call_count == 2

    def test_non_retryable_error_fails_after_a_single_attempt(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(error=ProviderAuthenticationError))
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        version = PublishedAgentVersionFactory(max_model_calls=5, max_retry_attempts=5)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.FAILED
        assert result.failure_code == "provider_authentication_failed"
        assert provider.call_count == 1


@pytest.mark.django_db
class TestScenarioCBudgetExceeded:
    def test_zero_model_call_budget_blocks_before_any_provider_call(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario())
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        version = PublishedAgentVersionFactory(max_model_calls=1, max_steps=1)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.BUDGET_EXCEEDED
        assert result.failure_code == "budget_exceeded:max_steps_reached"
        assert provider.call_count == 0

    def test_zero_token_budget_blocks_before_any_provider_call(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(input_tokens=5, output_tokens=5))
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        version = PublishedAgentVersionFactory(max_total_tokens=0)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.BUDGET_EXCEEDED
        assert result.failure_code == "budget_exceeded:max_total_tokens_reached"
        assert provider.call_count == 0

    def test_expired_wall_time_budget_blocks_before_any_provider_call(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario())
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        version = PublishedAgentVersionFactory(wall_time_limit_seconds=1)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        import time

        real_monotonic = time.monotonic()
        calls = {"count": 0}

        def fake_monotonic():
            # The first read (run-context start time, in graph.py) returns the
            # real clock; every later read (the budget check) jumps far
            # forward so the very first check observes an expired deadline.
            calls["count"] += 1
            return real_monotonic if calls["count"] == 1 else real_monotonic + 1000

        monkeypatch.setattr("agents.runtime.graph.time.monotonic", fake_monotonic)
        monkeypatch.setattr("agents.runtime.budgets.time.monotonic", fake_monotonic)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.BUDGET_EXCEEDED
        assert result.failure_code == "budget_exceeded:wall_time_limit_reached"
        assert provider.call_count == 0

    def test_budget_exceeded_records_a_safe_trace_event(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario())
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        version = PublishedAgentVersionFactory(max_total_tokens=0)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        result = services.execute_agent_run(run.id)

        budget_step = result.steps.get(step_type=AgentStepType.BUDGET_CHECKED)
        assert budget_step.safe_metadata["allowed"] is False


@pytest.mark.django_db
class TestScenarioDCrossWorkspaceLookup:
    def test_selector_404s_instead_of_leaking_existence(self):
        from django.http import Http404

        from agents import selectors
        from workspaces.tests.factories import WorkspaceFactory

        foreign_run = AgentRunFactory()
        with pytest.raises(Http404):
            selectors.agent_run_get_for_workspace_or_404(
                workspace=WorkspaceFactory(), run_id=foreign_run.id
            )


@pytest.mark.django_db
class TestScenarioEDuplicateExecutionClaim:
    def test_only_one_of_two_execution_attempts_completes_the_run(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="answer"))
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        run = AgentRunFactory()

        first = services.execute_agent_run(run.id)
        second = services.execute_agent_run(run.id)

        assert first.status == AgentRunStatus.SUCCEEDED
        assert second.status == AgentRunStatus.SUCCEEDED
        assert second.id == first.id
        # The provider was only ever called once; the second call observed
        # the already-terminal run rather than re-executing.
        assert provider.call_count == 1


@pytest.mark.django_db
class TestScenarioFProviderSecretSafety:
    def test_authentication_failure_never_leaks_a_credential(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(
            FakeLLMScenario(error=ProviderAuthenticationError, error_message="sk-super-secret-key")
        )
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        version = PublishedAgentVersionFactory(max_model_calls=1, max_retry_attempts=1)
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.FAILED
        assert "sk-super-secret-key" not in (result.failure_message_safe or "")
        for step in result.steps.all():
            assert "sk-super-secret-key" not in str(step.safe_metadata)
            assert "sk-super-secret-key" not in step.output_summary
            assert "sk-super-secret-key" not in step.input_summary


@pytest.mark.django_db
class TestScenarioGTerminalStateProtection:
    def test_succeeded_run_cannot_be_reopened_by_a_second_execution(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="answer"))
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        run = AgentRunFactory()
        services.execute_agent_run(run.id)
        run.refresh_from_db()
        assert run.status == AgentRunStatus.SUCCEEDED

        from accounts.tests.factories import UserFactory
        from agents.errors import AgentRunNotCancellableError

        with pytest.raises(AgentRunNotCancellableError):
            services.cancel_agent_run(workspace=run.workspace, run=run, actor=UserFactory())

        # A completion helper invoked again on a terminal run is a safe no-op.
        completed_again = services._complete_run(run, {"final_response": "different"})
        assert completed_again.final_response == "answer"


@pytest.mark.django_db
class TestProviderVersionMismatch:
    def test_version_declaring_a_different_provider_than_configured_fails_safely(self, settings):
        settings.AGENTS_LLM_PROVIDER = "fake"
        version = PublishedAgentVersionFactory(provider="openai", model="gpt-test")
        run = AgentRunFactory(agent_version=version, workspace=version.agent_definition.workspace)

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.FAILED
        assert result.failure_code == "provider_configuration_error"


@pytest.mark.django_db
class TestMalformedProviderResponse:
    def test_empty_response_text_is_treated_as_malformed(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(response=""))
        monkeypatch.setattr(services, "get_llm_provider", lambda: provider)
        run = AgentRunFactory()

        result = services.execute_agent_run(run.id)

        assert result.status == AgentRunStatus.FAILED
        assert result.failure_code == "provider_malformed_response"
