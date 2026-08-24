"""Typed, vendor-independent LLM request/response contracts.

Application and runtime code depends only on these dataclasses, never on a
vendor SDK's request/response objects. Nothing here carries hidden
chain-of-thought — only the final text, structured output (when requested),
and normalized provider metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

MessageRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class ToolDescriptor:
    """Safe provider-facing description derived from a trusted ToolSpec."""

    key: str
    display_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class LLMRequest:
    """A normalized request the runtime issues to any ``LLMProvider``."""

    messages: tuple[LLMMessage, ...]
    model: str
    tools: tuple[ToolDescriptor, ...] = ()
    temperature: float = 0.0
    max_output_tokens: int = 512
    structured_output_schema: dict[str, Any] | None = None
    timeout_seconds: float = 30.0
    correlation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class NormalizedToolCall:
    """A vendor-neutral tool-call request normalized out of a provider
    response (section 44-45). Provider adapters (e.g. the OpenAI adapter's
    function/tool-call representation) must translate into this type — the
    tool execution boundary never sees a vendor SDK object.

    ``tool_name``/``arguments`` are the model's untrusted proposal; nothing
    here is treated as authoritative execution context (section 20).
    """

    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    normalization_error: str | None = None


# Backward-compatible name used by the Phase 6 tests and callers. Both real
# and fake providers now travel through the NormalizedToolCall contract.
ToolCallRequest = NormalizedToolCall


@dataclass(frozen=True)
class NormalizedHandoffRequest:
    """A vendor-neutral human-handoff request normalized out of a provider
    response (Phase 9 Block 5, section 7). Deliberately carries only
    ``reason_code``/``summary`` — no ``workspace_id``, ``assigned_to``,
    ``staff_role``, ``ticket_id``, or priority field exists on this type at
    all, so the model has no *shape* through which to propose one (section
    7, 10-12, 67-68): those facts are always server-derived from the
    ``AgentRun`` the request belongs to, never from provider output.

    Both fields are the model's untrusted proposal (section 29) — safe
    plain text, never treated as executable/authoritative until
    ``agents.services`` validates ``reason_code`` against the server-owned
    ``HumanHandoffReason`` enum and persists ``summary`` as a bounded,
    redaction-safe field.
    """

    reason_code: str
    summary: str


MAX_NORMALIZED_TOOL_ARGUMENT_BYTES = 8000
MAX_NORMALIZED_HANDOFF_SUMMARY_CHARS = 2000


def normalize_handoff_request(*, reason_code: Any, summary: Any) -> NormalizedHandoffRequest | None:
    """Shape-only normalization (section 28-29): clamps to safe plain-text
    strings. The actual server-owned reason-code taxonomy is enforced later,
    in ``agents.services``, not here — this function only guarantees the
    orchestration graph never carries a non-string/oversized value.
    """
    if not isinstance(reason_code, str) or not isinstance(summary, str):
        return None
    reason_code = reason_code.strip()
    summary = summary.strip()[:MAX_NORMALIZED_HANDOFF_SUMMARY_CHARS]
    if not reason_code or not summary:
        return None
    return NormalizedHandoffRequest(reason_code=reason_code, summary=summary)


def normalize_tool_call(
    *, provider_call_id: str, tool_key: str, raw_arguments: Any
) -> NormalizedToolCall:
    """Parse dict/JSON arguments without ever evaluating model-generated code."""
    try:
        if isinstance(raw_arguments, str):
            if len(raw_arguments.encode("utf-8")) > MAX_NORMALIZED_TOOL_ARGUMENT_BYTES:
                raise ValueError
            parsed = json.loads(raw_arguments)
        elif isinstance(raw_arguments, dict):
            if (
                len(json.dumps(raw_arguments, default=str).encode("utf-8"))
                > MAX_NORMALIZED_TOOL_ARGUMENT_BYTES
            ):
                raise ValueError
            parsed = raw_arguments
        else:
            raise ValueError
        if not isinstance(parsed, dict):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeError):
        return NormalizedToolCall(
            call_id=provider_call_id,
            tool_name=tool_key,
            arguments={},
            normalization_error="tool_arguments_malformed",
        )
    return NormalizedToolCall(
        call_id=provider_call_id,
        tool_name=tool_key,
        arguments=parsed,
    )


@dataclass(frozen=True)
class LLMResponse:
    """A normalized response. Never carries raw vendor SDK objects or hidden
    reasoning — only the final user-visible text, optional structured output,
    and safe operational metadata."""

    text: str
    provider: str
    model: str
    finish_reason: str
    usage: LLMUsage
    latency_ms: int
    provider_request_id: str | None = None
    structured_output: dict[str, Any] | None = None
    estimated_cost_usd: float | None = None
    tool_calls: tuple[NormalizedToolCall, ...] = ()
    # Phase 9 Block 5: a normalized human-handoff request, if the model
    # proposed one this turn. Independent of ``tool_calls`` — a handoff is
    # not a tool execution (it never creates a ToolExecution row, section
    # 41) — and takes precedence over any tool call in the same response
    # (section 9; see ``agents.runtime.graph._generate_response``).
    handoff_request: NormalizedHandoffRequest | None = None
