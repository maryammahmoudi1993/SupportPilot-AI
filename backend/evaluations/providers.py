"""Builds a deterministic, per-case fake LLM provider from seeded context.

Never touches the network (section 14). ``EvaluationSeededContext.llm_scenarios``
is a bounded, JSON-safe description of each expected model call — this module
is the only place that turns it into the real ``DeterministicFakeLLMProvider``
scenario objects the agent runtime consumes, so a malformed scenario fails
with a clear, safe error instead of silently misbehaving.
"""

from __future__ import annotations

from typing import Any

from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from agents.providers.schemas import NormalizedHandoffRequest, NormalizedToolCall

_ALLOWED_SCENARIO_KEYS = frozenset(
    {
        "response",
        "input_tokens",
        "output_tokens",
        "finish_reason",
        "latency_ms",
        "structured_output",
        "estimated_cost_usd",
        "tool_calls",
        "handoff_request",
    }
)


class InvalidLLMScenarioError(Exception):
    """Raised when ``llm_scenarios`` contains an unexpected shape."""


def _build_tool_calls(raw: list[dict] | None) -> tuple[NormalizedToolCall, ...]:
    if not raw:
        return ()
    calls = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or "tool_key" not in item:
            raise InvalidLLMScenarioError(f"tool_calls[{index}] must include 'tool_key'.")
        calls.append(
            NormalizedToolCall(
                call_id=str(item.get("call_id", f"eval-call-{index}")),
                tool_name=str(item["tool_key"]),
                arguments=dict(item.get("arguments", {})),
            )
        )
    return tuple(calls)


def _build_handoff_request(raw: dict | None) -> NormalizedHandoffRequest | None:
    if not raw:
        return None
    if "reason_code" not in raw or "summary" not in raw:
        raise InvalidLLMScenarioError("handoff_request must include 'reason_code' and 'summary'.")
    return NormalizedHandoffRequest(
        reason_code=str(raw["reason_code"]), summary=str(raw["summary"])
    )


def build_fake_llm_provider(llm_scenarios: list[dict[str, Any]]) -> DeterministicFakeLLMProvider:
    if not llm_scenarios:
        return DeterministicFakeLLMProvider()

    scenarios: list[FakeLLMScenario] = []
    for index, raw in enumerate(llm_scenarios):
        if not isinstance(raw, dict):
            raise InvalidLLMScenarioError(f"llm_scenarios[{index}] must be an object.")
        unexpected = set(raw) - _ALLOWED_SCENARIO_KEYS
        if unexpected:
            raise InvalidLLMScenarioError(
                f"llm_scenarios[{index}] has unexpected keys: {sorted(unexpected)}"
            )
        kwargs: dict[str, Any] = {
            key: raw[key] for key in raw if key not in {"tool_calls", "handoff_request"}
        }
        scenarios.append(
            FakeLLMScenario(
                tool_calls=_build_tool_calls(raw.get("tool_calls")),
                handoff_request=_build_handoff_request(raw.get("handoff_request")),
                **kwargs,
            )
        )
    return DeterministicFakeLLMProvider(scenarios=scenarios)
