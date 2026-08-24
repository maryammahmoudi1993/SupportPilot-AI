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

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from agents.models import AgentStepStatus, AgentStepType
from agents.providers.errors import ProviderError
from agents.providers.protocol import LLMProvider
from agents.providers.schemas import LLMMessage, LLMRequest, ToolDescriptor
from agents.tool_runtime import ToolResultContext

from .budgets import Budgets, check_budget
from .state import RuntimeState, initial_state

StepRecorder = Callable[..., None]
# Returns a safe outcome dict: {"succeeded", "output_summary", "error_code",
# "error_message"}. Never raises — the graph only ever sees normalized,
# already-safe results (agents.services wraps tools.execution.execute_tool).
ExecuteToolFn = Callable[[str, dict[str, Any], str | None], dict[str, Any]]
CancellationCheck = Callable[[], bool]
# Phase 9 Block 5: pure, stateless validation only — {"ok": True,
# "reason_code", "summary"} or {"ok": False, "error_code", "error_message"}.
# Never persists a HumanHandoff row itself (section 54; see
# ``agents.services._complete_run_as_handoff``, which does that atomically
# with the AgentRun's own terminal transition).
RequestHandoffFn = Callable[[str, str], dict[str, Any]]


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
    initial_messages: tuple[LLMMessage, ...] | None = None
    tool_descriptors: tuple[ToolDescriptor, ...] = ()
    agent_run_id: str | None = None
    is_cancelled: CancellationCheck | None = None
    request_handoff: RequestHandoffFn | None = None


def _prepare_run(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    ctx.record_step(
        step_type=AgentStepType.RUN_STARTED,
        status=AgentStepStatus.SUCCEEDED,
        input_summary=f"{len(state['input_message'])} chars",
    )
    return {"step_count": state["step_count"] + 1}


def _check_budget(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    if ctx.is_cancelled is not None and ctx.is_cancelled():
        return {"cancelled": True}
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
    if ctx.initial_messages is not None:
        messages.extend(ctx.initial_messages)
    else:
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
        tools=ctx.tool_descriptors,
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
            "tool_calls_received": len(response.tool_calls),
            "tool_calls_considered": min(1, len(response.tool_calls)),
            "ignored_tool_call_count": max(0, len(response.tool_calls) - 1),
        },
    )
    # Phase 9 Block 5 (section 9, 44): a handoff request takes deterministic
    # precedence over any tool call proposed in the same turn — if the model
    # signals it cannot safely proceed, no tool executes this turn. Only
    # reachable when the runtime actually supports handoff (``ctx.request_handoff``
    # is bound); otherwise a handoff-capable response falls through to
    # ordinary tool/final-response handling like any other model turn.
    handoff_call = response.handoff_request if ctx.request_handoff is not None else None
    if handoff_call is not None:
        ctx.record_step(
            step_type=AgentStepType.HANDOFF_REQUESTED,
            status=AgentStepStatus.SUCCEEDED,
            safe_metadata={"event": "handoff_requested"},
        )
    # Only the first proposed tool call is honored — one bounded round-trip
    # per model turn keeps the graph's termination argument simple (extra
    # calls in the same turn are ignored, not queued; section 43). Ignored
    # entirely when a handoff was requested this turn (precedence above).
    tool_call = (
        None
        if handoff_call is not None
        else (response.tool_calls[0] if response.tool_calls else None)
    )
    if tool_call is not None:
        ctx.record_step(
            step_type=AgentStepType.REQUEST_NORMALIZED,
            status=AgentStepStatus.SUCCEEDED,
            safe_metadata={
                "event": "tool_call_received",
                "tool_key": tool_call.tool_name,
                "tool_calls_received": len(response.tool_calls),
                "ignored_tool_call_count": max(0, len(response.tool_calls) - 1),
            },
        )
    model_turn = state["model_call_count"] + 1
    idempotency_key = None
    if tool_call is not None:
        canonical = json.dumps(tool_call.arguments, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(f"{tool_call.tool_name}:{canonical}".encode()).hexdigest()[:24]
        idempotency_key = f"agent:{ctx.agent_run_id or 'unknown'}:turn:{model_turn}:{digest}"
    prior_cost = state.get("estimated_cost_usd")
    turn_cost = response.estimated_cost_usd
    accumulated_cost = (
        float(Decimal(str(prior_cost or 0)) + Decimal(str(turn_cost or 0)))
        if prior_cost is not None or turn_cost is not None
        else None
    )
    return {
        "model_call_count": state["model_call_count"] + 1,
        "step_count": state["step_count"] + 1,
        "attempt": attempt,
        "input_tokens": state["input_tokens"] + response.usage.input_tokens,
        "output_tokens": state["output_tokens"] + response.usage.output_tokens,
        "total_tokens": state["total_tokens"] + response.usage.total_tokens,
        "estimated_cost_usd": accumulated_cost,
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
                "normalization_error": tool_call.normalization_error,
                "idempotency_key": idempotency_key,
            }
            if tool_call
            else None
        ),
        "tool_result_summary": None,
        "pending_handoff_request": (
            {"reason_code": handoff_call.reason_code, "summary": handoff_call.summary}
            if handoff_call is not None
            else None
        ),
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
    if state.get("pending_handoff_request") and ctx.request_handoff is not None:
        return "handoff_request"
    if state.get("pending_tool_call") and ctx.execute_tool is not None:
        return "tool_request"
    return "continue"


def _execute_tool_call(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    call = state.get("pending_tool_call")
    if not call or ctx.execute_tool is None:  # pragma: no cover - guarded by routing
        return {"pending_tool_call": None}
    if ctx.is_cancelled is not None and ctx.is_cancelled():
        return {"pending_tool_call": None, "cancelled": True}
    if call.get("normalization_error"):
        result_context = ToolResultContext(
            tool_key=call["tool_name"],
            status="failed",
            error_code=call["normalization_error"],
        )
        model_result = result_context.as_model_message()
        ctx.record_step(
            step_type=AgentStepType.REQUEST_NORMALIZED,
            status=AgentStepStatus.SUCCEEDED,
            safe_metadata={
                "event": "tool_result_prepared",
                "tool_key": call["tool_name"],
                "status": "failed",
                "error_code": call["normalization_error"],
            },
        )
        return {
            "pending_tool_call": None,
            "step_count": state["step_count"] + 1,
            "tool_result_summary": model_result,
        }
    outcome = ctx.execute_tool(call["tool_name"], call["arguments"], call.get("idempotency_key"))
    update: dict[str, Any] = {
        "pending_tool_call": None,
        "step_count": state["step_count"] + 1,
    }
    if outcome.get("approval_required"):
        update["safe_error_code"] = outcome.get("error_code") or "tool_execution_failed"
        update["safe_error_message"] = outcome.get("error_message") or "The requested tool failed."
        update["retryable_error"] = False
    elif outcome.get("budget_exceeded"):
        update["budget_exceeded"] = True
        update["budget_exceeded_reason"] = outcome.get("budget_reason")
    elif outcome.get("terminal"):
        update["safe_error_code"] = outcome.get("error_code") or "tool_execution_failed"
        update["safe_error_message"] = outcome.get("error_message") or "The requested tool failed."
        update["retryable_error"] = False
    else:
        update["tool_result_summary"] = outcome.get("model_result", "")
        ctx.record_step(
            step_type=AgentStepType.REQUEST_NORMALIZED,
            status=AgentStepStatus.SUCCEEDED,
            safe_metadata={
                "event": "tool_result_prepared",
                "tool_key": call["tool_name"],
                "status": outcome.get("result_status", "failed"),
                "error_code": outcome.get("error_code", ""),
                "reused": bool(outcome.get("reused", False)),
            },
        )
    return update


def _route_after_tool(state: RuntimeState) -> str:
    return (
        "end"
        if state.get("safe_error_code") or state.get("budget_exceeded") or state.get("cancelled")
        else "continue"
    )


def _execute_handoff_request(ctx: RunContext, state: RuntimeState) -> dict[str, Any]:
    """Phase 9 Block 5 (section 8, 24, 41, 54, 87): validate the requested
    handoff and end the graph immediately — never loop back to
    ``check_budget``/``generate_response`` (a successful handoff needs no
    further model call to describe itself). The ``HumanHandoff`` row itself
    is *not* created here: only ``pending_handoff_request`` is consumed and
    a validated ``handoff_request`` fact returned, so the actual
    create-or-reuse write can happen atomically with the ``AgentRun``'s own
    terminal transition in ``agents.services._complete_run_as_handoff`` —
    closing the race where a concurrent cancellation could otherwise leave
    an orphaned active ``HumanHandoff`` for an already-cancelled run.
    """
    request = state.get("pending_handoff_request")
    if not request or ctx.request_handoff is None:  # pragma: no cover - guarded by routing
        return {"pending_handoff_request": None}
    if ctx.is_cancelled is not None and ctx.is_cancelled():
        return {"pending_handoff_request": None, "cancelled": True}
    validated = ctx.request_handoff(request["reason_code"], request["summary"])
    update: dict[str, Any] = {
        "pending_handoff_request": None,
        "step_count": state["step_count"] + 1,
    }
    if not validated.get("ok"):
        update["safe_error_code"] = validated.get("error_code") or "invalid_handoff_request"
        update["safe_error_message"] = (
            validated.get("error_message") or "The handoff request was invalid."
        )
        update["retryable_error"] = False
    else:
        update["handoff_request"] = {
            "reason_code": validated["reason_code"],
            "summary": validated["summary"],
        }
    return update


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
    graph.add_node("execute_handoff_request", lambda s: _execute_handoff_request(ctx, s))
    graph.add_node("validate_provider_result", lambda s: _validate_provider_result(ctx, s))
    graph.add_node("finalize_response", lambda s: _finalize_response(ctx, s))

    graph.add_edge(START, "prepare_run")
    graph.add_edge("prepare_run", "check_budget")
    graph.add_conditional_edges(
        "check_budget",
        lambda s: "exceeded" if s.get("budget_exceeded") or s.get("cancelled") else "proceed",
        {"exceeded": END, "proceed": "generate_response"},
    )
    graph.add_conditional_edges(
        "generate_response",
        lambda s: _route_after_generate(ctx, s),
        {
            "retry": "check_budget",
            "tool_request": "execute_tool_call",
            "handoff_request": "execute_handoff_request",
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
    # A handoff request is always terminal for the graph (section 24, 87):
    # success or failure, it never routes back to check_budget/generate_response.
    graph.add_edge("execute_handoff_request", END)
    graph.add_conditional_edges(
        "validate_provider_result",
        lambda s: "error" if s.get("safe_error_code") else "ok",
        {"error": END, "ok": "finalize_response"},
    )
    graph.add_edge("finalize_response", END)
    return graph.compile()


def run_graph(ctx: RunContext, *, input_message: str) -> RuntimeState:
    graph = build_graph(ctx)
    recursion_limit = max(25, ctx.budgets.max_steps * 4 + ctx.budgets.max_model_calls * 4)
    result: Any = graph.invoke(
        initial_state(input_message=input_message), config={"recursion_limit": recursion_limit}
    )
    return cast(RuntimeState, result)


def build_resume_graph(ctx: RunContext):
    """The same bounded graph as :func:`build_graph`, entered directly at
    ``check_budget`` instead of ``prepare_run`` (section 57-58, 66).

    Used only after a paused tool action's approval is granted: the tool
    call has already been resolved by ``tools.execution.resume_after_approval``
    (never replayed here), so the graph resumes exactly where Phase 6's
    normal successful-tool-call path already routes to — through
    ``check_budget`` (which re-checks the run's *persisted* counters, all
    strictly increasing, so termination still holds) and on to a bounded
    follow-up model turn. Every node function is identical to the main
    graph's — only the entry edge and the omission of ``prepare_run``
    (which only records a step and increments ``step_count`` for the very
    first entry) differ.
    """
    graph = StateGraph(RuntimeState)
    graph.add_node("check_budget", lambda s: _check_budget(ctx, s))
    graph.add_node("generate_response", lambda s: _generate_response(ctx, s))
    graph.add_node("execute_tool_call", lambda s: _execute_tool_call(ctx, s))
    graph.add_node("execute_handoff_request", lambda s: _execute_handoff_request(ctx, s))
    graph.add_node("validate_provider_result", lambda s: _validate_provider_result(ctx, s))
    graph.add_node("finalize_response", lambda s: _finalize_response(ctx, s))

    graph.add_edge(START, "check_budget")
    graph.add_conditional_edges(
        "check_budget",
        lambda s: "exceeded" if s.get("budget_exceeded") or s.get("cancelled") else "proceed",
        {"exceeded": END, "proceed": "generate_response"},
    )
    graph.add_conditional_edges(
        "generate_response",
        lambda s: _route_after_generate(ctx, s),
        {
            "retry": "check_budget",
            "tool_request": "execute_tool_call",
            "handoff_request": "execute_handoff_request",
            "continue": "validate_provider_result",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "execute_tool_call",
        lambda s: _route_after_tool(s),
        {"continue": "check_budget", "end": END},
    )
    graph.add_edge("execute_handoff_request", END)
    graph.add_conditional_edges(
        "validate_provider_result",
        lambda s: "error" if s.get("safe_error_code") else "ok",
        {"error": END, "ok": "finalize_response"},
    )
    graph.add_edge("finalize_response", END)
    return graph.compile()


def resume_state_after_tool(
    *,
    input_message: str,
    model_call_count: int,
    step_count: int,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    estimated_cost_usd: float | None,
    tool_result_summary: str,
) -> RuntimeState:
    """Reconstruct the graph state as it would look immediately after a
    successful, non-paused tool call — the exact point Phase 6's own
    ``execute_tool_call`` node hands off to ``check_budget`` on its
    "continue" edge. Every counter comes from the run's own persisted
    values (section 153-155: waiting for approval, and the resume itself,
    must never reset or inflate the run's budget)."""
    state = initial_state(input_message=input_message)
    state.update(
        {
            "model_call_count": model_call_count,
            "step_count": step_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "tool_result_summary": tool_result_summary,
        }
    )
    return state


def run_resume_graph(ctx: RunContext, *, state: RuntimeState) -> RuntimeState:
    graph = build_resume_graph(ctx)
    recursion_limit = max(25, ctx.budgets.max_steps * 4 + ctx.budgets.max_model_calls * 4)
    result: Any = graph.invoke(state, config={"recursion_limit": recursion_limit})
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
    initial_messages: tuple[LLMMessage, ...] | None = None,
    tool_descriptors: tuple[ToolDescriptor, ...] = (),
    agent_run_id: str | None = None,
    is_cancelled: CancellationCheck | None = None,
    request_handoff: RequestHandoffFn | None = None,
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
        initial_messages=initial_messages,
        tool_descriptors=tool_descriptors,
        agent_run_id=agent_run_id,
        is_cancelled=is_cancelled,
        request_handoff=request_handoff,
    )
