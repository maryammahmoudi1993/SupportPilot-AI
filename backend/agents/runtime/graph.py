"""A deliberately small, bounded LangGraph state graph.

::

    START -> prepare_run -> check_budget -> generate_response
                                 ^                 |
                                 | (bounded retry) |
                                 +-----------------+
                                                    v
                                      validate_provider_result -> finalize_response -> END

Budget exhaustion or a non-retryable/attempt-exhausted provider failure
routes directly to END with a safe error/budget code in the returned state.
There is no unbounded loop: the retry edge is only taken while
``attempt < max_retry_attempts`` *and* ``model_call_count < max_model_calls``,
both of which are strictly increasing, so the graph always terminates.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from agents.models import AgentStepStatus, AgentStepType
from agents.providers.errors import ProviderError
from agents.providers.protocol import LLMProvider
from agents.providers.schemas import LLMMessage, LLMRequest

from .budgets import Budgets, check_budget
from .state import RuntimeState, initial_state

StepRecorder = Callable[..., None]
# Returns a safe outcome dict: {"succeeded", "output_summary", "error_code",
# "error_message"}. Never raises — the graph only ever sees normalized,
# already-safe results (agents.services wraps tools.execution.execute_tool).
ExecuteToolFn = Callable[[str, dict[str, Any], str | None], dict[str, Any]]


@dataclass
class RunContext:
    provider: LLMProvider
    budgets: Budgets
    model: str
    temperature: float
    max_output_tokens: int
    system_prompt: str
    correlation_id: str | None
    record_step: StepRecorder
    started_monotonic: float
    execute_tool: ExecuteToolFn | None = None


def _prepare_run(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    ctx.record_step(
        step_type=AgentStepType.RUN_STARTED,
        status=AgentStepStatus.SUCCEEDED,
        input_summary=f"{len(state['input_message'])} chars",
    )
    return {"step_count": state["step_count"] + 1}


def _check_budget(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    cost = Decimal(str(state["estimated_cost_usd"])) if state.get("estimated_cost_usd") else None
    result = check_budget(
        budgets=ctx.budgets,
        model_call_count=state["model_call_count"],
        step_count=state["step_count"],
        total_tokens=state["total_tokens"],
        estimated_cost_usd=cost,
        started_monotonic=ctx.started_monotonic,
    )
    ctx.record_step(
        step_type=AgentStepType.BUDGET_CHECKED,
        status=AgentStepStatus.SUCCEEDED if result.allowed else AgentStepStatus.FAILED,
        safe_metadata={"allowed": result.allowed, "reason": result.reason},
    )
    update: dict[str, Any] = {"step_count": state["step_count"] + 1}
    if not result.allowed:
        update["budget_exceeded"] = True
        update["budget_exceeded_reason"] = result.reason
    return update


def _generate_response(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    if state.get("budget_exceeded"):
        return {}
    messages: list[LLMMessage] = []
    if ctx.system_prompt:
        messages.append(LLMMessage(role="system", content=ctx.system_prompt))
    messages.append(LLMMessage(role="user", content=state["input_message"]))
    if state.get("tool_result_summary"):
        # Minimal grounding: the model's next call sees a plain-text summary
        # of the tool result. Full multi-turn tool-call transcripts are
        # explicitly out of scope for Phase 6 (section 42-43).
        messages.append(
            LLMMessage(role="user", content=f"[tool_result] {state['tool_result_summary']}")
        )
    request = LLMRequest(
        messages=tuple(messages),
        model=ctx.model,
        temperature=ctx.temperature,
        max_output_tokens=ctx.max_output_tokens,
        timeout_seconds=ctx.budgets.provider_timeout_seconds,
        correlation_id=ctx.correlation_id,
    )
    attempt = state.get("attempt", 0) + 1
    ctx.record_step(
        step_type=AgentStepType.PROVIDER_CALL_STARTED,
        status=AgentStepStatus.STARTED,
        provider=ctx.provider.name,
        model=ctx.model,
    )
    try:
        response = ctx.provider.generate(request)
    except ProviderError as exc:
        ctx.record_step(
            step_type=AgentStepType.PROVIDER_CALL_FAILED,
            status=AgentStepStatus.FAILED,
            provider=ctx.provider.name,
            model=ctx.model,
            error_code=exc.code,
        )
        return {
            "model_call_count": state["model_call_count"] + 1,
            "step_count": state["step_count"] + 1,
            "attempt": attempt,
            "safe_error_code": exc.code,
            "safe_error_message": exc.safe_message,
            "retryable_error": exc.retryable,
        }

    ctx.record_step(
        step_type=AgentStepType.PROVIDER_CALL_SUCCEEDED,
        status=AgentStepStatus.SUCCEEDED,
        provider=response.provider,
        model=response.model,
        latency_ms=response.latency_ms,
        safe_metadata={
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "finish_reason": response.finish_reason,
        },
    )
    # Only the first proposed tool call is honored — one bounded round-trip
    # per model turn keeps the graph's termination argument simple (extra
    # calls in the same turn are ignored, not queued; section 43).
    tool_call = response.tool_calls[0] if response.tool_calls else None
    return {
        "model_call_count": state["model_call_count"] + 1,
        "step_count": state["step_count"] + 1,
        "attempt": attempt,
        "input_tokens": state["input_tokens"] + response.usage.input_tokens,
        "output_tokens": state["output_tokens"] + response.usage.output_tokens,
        "total_tokens": state["total_tokens"] + response.usage.total_tokens,
        "estimated_cost_usd": response.estimated_cost_usd,
        "final_response": response.text,
        "finish_reason": response.finish_reason,
        "structured_output": response.structured_output,
        "provider_request_id": response.provider_request_id,
        "safe_error_code": None,
        "safe_error_message": None,
        "retryable_error": False,
        "pending_tool_call": (
            {
                "call_id": tool_call.call_id,
                "tool_name": tool_call.tool_name,
                "arguments": tool_call.arguments,
            }
            if tool_call
            else None
        ),
        "tool_result_summary": None,
    }


def _route_after_generate(ctx: RunContext, state: RuntimeState) -> str:
    if state.get("budget_exceeded"):
        return "end"
    if state.get("safe_error_code"):
        can_retry = (
            state.get("retryable_error", False)
            and state.get("attempt", 0) < ctx.budgets.max_retry_attempts
            and state["model_call_count"] < ctx.budgets.max_model_calls
        )
        return "retry" if can_retry else "end"
    if state.get("pending_tool_call") and ctx.execute_tool is not None:
        return "tool_request"
    return "continue"


def _execute_tool_call(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    call = state.get("pending_tool_call")
    if not call or ctx.execute_tool is None:  # pragma: no cover - guarded by routing
        return {"pending_tool_call": None}
    outcome = ctx.execute_tool(call["tool_name"], call["arguments"], call.get("idempotency_key"))
    update: dict[str, Any] = {
        "pending_tool_call": None,
        "step_count": state["step_count"] + 1,
    }
    if outcome.get("succeeded"):
        update["tool_result_summary"] = outcome.get("output_summary", "")
    else:
        update["safe_error_code"] = outcome.get("error_code") or "tool_execution_failed"
        update["safe_error_message"] = outcome.get("error_message") or "The requested tool failed."
        update["retryable_error"] = False
    return update


def _route_after_tool(state: RuntimeState) -> str:
    return "end" if state.get("safe_error_code") else "continue"


def _validate_provider_result(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    if not state.get("final_response"):
        return {
            "safe_error_code": "provider_malformed_response",
            "safe_error_message": "The AI provider returned an empty response.",
            "retryable_error": False,
        }
    return {}


def _finalize_response(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    ctx.record_step(
        step_type=AgentStepType.RESPONSE_FINALIZED,
        status=AgentStepStatus.SUCCEEDED,
        output_summary=f"{len(state['final_response'])} chars",
    )
    return {"step_count": state["step_count"] + 1}


def build_graph(ctx: RunContext):
    graph = StateGraph(RuntimeState)
    graph.add_node("prepare_run", lambda s: _prepare_run(ctx, s))
    graph.add_node("check_budget", lambda s: _check_budget(ctx, s))
    graph.add_node("generate_response", lambda s: _generate_response(ctx, s))
    graph.add_node("execute_tool_call", lambda s: _execute_tool_call(ctx, s))
    graph.add_node("validate_provider_result", lambda s: _validate_provider_result(ctx, s))
    graph.add_node("finalize_response", lambda s: _finalize_response(ctx, s))

    graph.add_edge(START, "prepare_run")
    graph.add_edge("prepare_run", "check_budget")
    graph.add_conditional_edges(
        "check_budget",
        lambda s: "exceeded" if s.get("budget_exceeded") else "proceed",
        {"exceeded": END, "proceed": "generate_response"},
    )
    graph.add_conditional_edges(
        "generate_response",
        lambda s: _route_after_generate(ctx, s),
        {
            "retry": "check_budget",
            "tool_request": "execute_tool_call",
            "continue": "validate_provider_result",
            "end": END,
        },
    )
    # Bounded continuation: a successful tool call routes back through
    # check_budget (which re-checks model_call_count/step_count/wall time,
    # all strictly increasing) before another provider call is scheduled —
    # never straight back to generate_response.
    graph.add_conditional_edges(
        "execute_tool_call",
        lambda s: _route_after_tool(s),
        {"continue": "check_budget", "end": END},
    )
    graph.add_conditional_edges(
        "validate_provider_result",
        lambda s: "error" if s.get("safe_error_code") else "ok",
        {"error": END, "ok": "finalize_response"},
    )
    graph.add_edge("finalize_response", END)
    return graph.compile()


def run_graph(ctx: RunContext, *, input_message: str) -> RuntimeState:
    graph = build_graph(ctx)
    result: Any = graph.invoke(initial_state(input_message=input_message))
    return cast(RuntimeState, result)


def new_run_context(
    *,
    provider: LLMProvider,
    budgets: Budgets,
    model: str,
    temperature: float,
    max_output_tokens: int,
    system_prompt: str,
    correlation_id: str | None,
    record_step: StepRecorder,
    execute_tool: ExecuteToolFn | None = None,
) -> RunContext:
    return RunContext(
        provider=provider,
        budgets=budgets,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        system_prompt=system_prompt,
        correlation_id=correlation_id,
        record_step=record_step,
        started_monotonic=time.monotonic(),
        execute_tool=execute_tool,
    )
