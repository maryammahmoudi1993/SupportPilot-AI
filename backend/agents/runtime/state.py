"""Explicit typed runtime state passed through the bounded execution graph.

Only stable, typed fields travel through the graph — never a raw ORM object
and never hidden chain-of-thought. ``safe_error_code``/``safe_error_message``
are the only failure channel; both are safe to persist and to surface to a
caller.
"""

from __future__ import annotations

from typing import Any, TypedDict


class RuntimeState(TypedDict, total=False):
    input_message: str
    model_call_count: int
    step_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    attempt: int
    final_response: str
    finish_reason: str
    structured_output: dict[str, Any] | None
    provider_request_id: str | None
    budget_exceeded: bool
    budget_exceeded_reason: str | None
    safe_error_code: str | None
    safe_error_message: str | None
    retryable_error: bool
    cancelled: bool
    # Bounded tool round-trip (section 42-43): at most one pending tool call
    # is carried at a time and it is always cleared before the next
    # provider call, so the graph can never accumulate an unbounded queue.
    pending_tool_call: dict[str, Any] | None
    tool_result_summary: str | None


def initial_state(*, input_message: str) -> RuntimeState:
    return RuntimeState(
        input_message=input_message,
        model_call_count=0,
        step_count=0,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        estimated_cost_usd=None,
        attempt=0,
        final_response="",
        finish_reason="",
        structured_output=None,
        provider_request_id=None,
        budget_exceeded=False,
        budget_exceeded_reason=None,
        safe_error_code=None,
        safe_error_message=None,
        retryable_error=False,
        cancelled=False,
        pending_tool_call=None,
        tool_result_summary=None,
    )
