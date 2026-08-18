import pytest

from agents.providers.errors import (
    ProviderAuthenticationError,
    ProviderRateLimitedError,
    ProviderTemporarilyUnavailableError,
    ProviderTimeoutError,
)
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.providers.schemas import LLMMessage, LLMRequest


def _request(model="fake-model-1"):
    return LLMRequest(messages=(LLMMessage(role="user", content="hello"),), model=model)


class TestDeterministicFakeLLMProvider:
    def test_default_scenario_is_a_successful_response(self):
        provider = DeterministicFakeLLMProvider()
        response = provider.generate(_request())
        assert response.text == "This is a deterministic fake response."
        assert response.provider == "fake"
        assert response.usage.total_tokens == 15
        assert response.finish_reason == "stop"

    def test_configured_scenario_is_deterministic_across_calls(self):
        scenario = FakeLLMScenario(
            response="Refunds require order verification.", input_tokens=42, output_tokens=8
        )
        provider = DeterministicFakeLLMProvider(scenario)
        first = provider.generate(_request())
        second = DeterministicFakeLLMProvider(scenario).generate(_request())
        assert first.text == second.text == "Refunds require order verification."
        assert first.usage.input_tokens == second.usage.input_tokens == 42

    def test_scenario_sequence_replays_in_order_then_repeats_last(self):
        provider = DeterministicFakeLLMProvider(
            [FakeLLMScenario(response="first"), FakeLLMScenario(response="second")]
        )
        assert provider.generate(_request()).text == "first"
        assert provider.generate(_request()).text == "second"
        assert provider.generate(_request()).text == "second"
        assert provider.call_count == 3

    def test_never_touches_the_network(self):
        # A deterministic provider must not import/require any HTTP client.
        import agents.providers.fake as fake_module

        assert "requests" not in dir(fake_module)
        assert "httpx" not in dir(fake_module)

    @pytest.mark.parametrize(
        "error_cls",
        [
            ProviderAuthenticationError,
            ProviderRateLimitedError,
            ProviderTimeoutError,
            ProviderTemporarilyUnavailableError,
        ],
    )
    def test_configured_error_scenarios_raise_normalized_errors(self, error_cls):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(error=error_cls))
        with pytest.raises(error_cls):
            provider.generate(_request())

    def test_error_scenario_does_not_increment_usage_side_effects(self):
        provider = DeterministicFakeLLMProvider(FakeLLMScenario(error=ProviderTimeoutError))
        with pytest.raises(ProviderTimeoutError):
            provider.generate(_request())
        assert provider.call_count == 1

    def test_structured_output_and_cost_are_passed_through(self):
        scenario = FakeLLMScenario(
            structured_output={"intent": "refund_request"}, estimated_cost_usd=0.002
        )
        response = DeterministicFakeLLMProvider(scenario).generate(_request())
        assert response.structured_output == {"intent": "refund_request"}
        assert response.estimated_cost_usd == 0.002
