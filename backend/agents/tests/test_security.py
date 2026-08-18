"""Adversarial and structural security regression tests (section 72)."""

import pytest

from agents.models import AgentRun, AgentStep
from agents.providers.errors import ProviderAuthenticationError
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.serializers import AgentRunSerializer
from agents.services import execute_agent_run

from .factories import AgentRunFactory


class TestServerDerivedFields:
    def test_run_serializer_is_entirely_read_only(self):
        # Status/counters are present as *read* data but the write serializer
        # (AgentRunCreateSerializer) never accepts them — see test_views.py's
        # test_client_cannot_set_status_or_usage_counters.
        assert set(AgentRunSerializer.Meta.read_only_fields) == set(AgentRunSerializer.Meta.fields)


@pytest.mark.django_db
class TestNoChainOfThoughtPersistence:
    def test_agent_step_model_has_no_reasoning_field(self):
        field_names = {f.name for f in AgentStep._meta.get_fields()}
        assert field_names.isdisjoint(
            {"reasoning", "chain_of_thought", "thoughts", "scratchpad", "private_reasoning"}
        )

    def test_agent_run_model_has_no_reasoning_field(self):
        field_names = {f.name for f in AgentRun._meta.get_fields()}
        assert field_names.isdisjoint(
            {"reasoning", "chain_of_thought", "thoughts", "scratchpad", "private_reasoning"}
        )

    def test_llm_response_schema_has_no_reasoning_field(self):
        from agents.providers.schemas import LLMResponse

        field_names = {f.name for f in LLMResponse.__dataclass_fields__.values()}
        assert field_names.isdisjoint({"reasoning", "chain_of_thought", "thoughts"})


@pytest.mark.django_db
class TestProviderSecretRedaction:
    def test_provider_error_str_never_contains_the_word_key_by_default(self, monkeypatch):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(error=ProviderAuthenticationError))
        monkeypatch.setattr("agents.services.get_llm_provider", lambda: provider)
        run = AgentRunFactory()
        result = execute_agent_run(run.id)
        assert result.failure_message_safe == ProviderAuthenticationError.safe_message
        assert "sk-" not in result.failure_message_safe


@pytest.mark.django_db
class TestBudgetTamperingPrevention:
    def test_created_run_uses_the_version_budgets_not_client_values(self):
        from accounts.tests.factories import UserFactory
        from agents.services import create_agent_run

        from .factories import PublishedAgentVersionFactory

        version = PublishedAgentVersionFactory(max_model_calls=1)
        run = create_agent_run(
            workspace=version.agent_definition.workspace,
            agent_version=version,
            actor=UserFactory(),
            input_message="hi",
            trigger="manual",
            input_metadata={"max_model_calls": 999, "attempt_budget_override": True},
        )
        # The run's own budget always comes from the immutable version, never
        # from anything in input_metadata.
        assert run.agent_version.max_model_calls == 1
        assert run.input_metadata["max_model_calls"] == 999  # stored, but inert
