"""Deterministic, offline LLM provider for tests, CI, and local development.

Never touches the network. Behavior is entirely explicit: callers configure a
sequence of ``FakeLLMScenario`` objects and the provider replays them in
order, repeating the last scenario for any call beyond the configured
sequence. This keeps tests free of magic strings scattered through
assertions — the scenario *is* the fixture.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .errors import ProviderError
from .schemas import LLMRequest, LLMResponse, LLMUsage, NormalizedHandoffRequest, ToolCallRequest


@dataclass(frozen=True)
class FakeLLMScenario:
    """One deterministic outcome for a single ``generate`` call.

    Set ``error`` to a ``ProviderError`` subclass to simulate a failure
    instead of a successful response. Set ``tool_calls`` to make this
    scenario propose a bounded tool round-trip instead of a final answer.
    Set ``handoff_request`` to make this scenario propose a human handoff
    instead (Phase 9 Block 5) — takes precedence over ``tool_calls`` when
    both are set, mirroring the real routing precedence.
    """

    response: str = "This is a deterministic fake response."
    input_tokens: int = 10
    output_tokens: int = 5
    finish_reason: str = "stop"
    latency_ms: int = 5
    structured_output: dict[str, Any] | None = None
    estimated_cost_usd: float | None = None
    provider_request_id: str = "fake-request-id"
    error: type[ProviderError] | None = None
    error_message: str | None = None
    tool_calls: tuple[ToolCallRequest, ...] = ()
    handoff_request: NormalizedHandoffRequest | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class DeterministicFakeLLMProvider:
    """Configurable, deterministic ``LLMProvider`` implementation."""

    name = "fake"

    def __init__(
        self, scenarios: Sequence[FakeLLMScenario] | FakeLLMScenario | None = None
    ) -> None:
        if scenarios is None:
            scenarios = [FakeLLMScenario()]
        elif isinstance(scenarios, FakeLLMScenario):
            scenarios = [scenarios]
        self._scenarios: list[FakeLLMScenario] = list(scenarios)
        self.call_count = 0
        self.requests: list[LLMRequest] = []

    def _next_scenario(self) -> FakeLLMScenario:
        index = min(self.call_count, len(self._scenarios) - 1)
        return self._scenarios[index]

    def generate(self, request: LLMRequest) -> LLMResponse:
        scenario = self._next_scenario()
        self.requests.append(request)
        self.call_count += 1
        if scenario.error is not None:
            raise scenario.error(scenario.error_message)
        return LLMResponse(
            text=scenario.response,
            provider=self.name,
            model=request.model,
            finish_reason=scenario.finish_reason,
            usage=LLMUsage(
                input_tokens=scenario.input_tokens,
                output_tokens=scenario.output_tokens,
                total_tokens=scenario.total_tokens,
            ),
            latency_ms=scenario.latency_ms,
            provider_request_id=scenario.provider_request_id,
            structured_output=scenario.structured_output,
            estimated_cost_usd=scenario.estimated_cost_usd,
            tool_calls=scenario.tool_calls,
            handoff_request=scenario.handoff_request,
        )
