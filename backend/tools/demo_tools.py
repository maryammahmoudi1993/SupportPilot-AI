"""Deterministic, safe demonstration tools (section 29 of the Phase 6 brief).

These prove the execution platform end-to-end — input validation, output
validation, registry lookup, persistence, idempotency, timeouts, and error
normalization — without touching any real business system. No real
integration (Stripe, Calendar, CRM, email) is implemented in this phase.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    IdempotencyMode,
    RetryPolicy,
    RiskLevel,
    SideEffectType,
    Tool,
    ToolExecutionContext,
    ToolSpec,
)
from .errors import ToolExecutionFailedError

MAX_STRING_LENGTH = 2000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# demo.echo
# --------------------------------------------------------------------------


class EchoInput(StrictModel):
    message: str = Field(min_length=1, max_length=MAX_STRING_LENGTH)


class EchoOutput(StrictModel):
    echoed: str


def _echo_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, EchoInput)
    return EchoOutput(echoed=arguments.message)


ECHO_TOOL = Tool(
    spec=ToolSpec(
        key="demo.echo",
        display_name="Echo",
        description=(
            "Deterministically echoes back the provided message. Read-only, no side effects."
        ),
        input_model=EchoInput,
        output_model=EchoOutput,
        risk_level=RiskLevel.READ_ONLY,
        side_effect_type=SideEffectType.NONE,
        default_timeout_seconds=5.0,
        max_timeout_seconds=10.0,
        retry_policy=RetryPolicy(max_retries=0),
        idempotency_mode=IdempotencyMode.SAFE,
    ),
    handler=_echo_handler,
)


# --------------------------------------------------------------------------
# demo.add
# --------------------------------------------------------------------------


class AddInput(StrictModel):
    a: int = Field(ge=-1_000_000, le=1_000_000)
    b: int = Field(ge=-1_000_000, le=1_000_000)


class AddOutput(StrictModel):
    sum: int


def _add_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    assert isinstance(arguments, AddInput)
    return AddOutput(sum=arguments.a + arguments.b)


ADD_TOOL = Tool(
    spec=ToolSpec(
        key="demo.add",
        display_name="Add",
        description="Deterministically adds two integers. Read-only, no side effects.",
        input_model=AddInput,
        output_model=AddOutput,
        risk_level=RiskLevel.READ_ONLY,
        side_effect_type=SideEffectType.NONE,
        default_timeout_seconds=5.0,
        max_timeout_seconds=10.0,
        retry_policy=RetryPolicy(max_retries=0),
        idempotency_mode=IdempotencyMode.SAFE,
    ),
    handler=_add_handler,
)


# --------------------------------------------------------------------------
# demo.flaky — deterministic retryable-then-succeeds handler used to prove
# retry semantics outside of tests too (still fully offline/deterministic;
# no randomness, no network, no filesystem, no clock reliance beyond a
# monotonic sleep for the timeout demonstration).
# --------------------------------------------------------------------------


class FlakyInput(StrictModel):
    fail_attempts: int = Field(ge=0, le=5, default=0)
    sleep_seconds: float = Field(ge=0, le=5, default=0)


class FlakyOutput(StrictModel):
    attempts_before_success: int


def _flaky_handler(*, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
    # Attempt count is derived from context, injected by the execution
    # service via a module-level counter keyed by tool_execution_id so the
    # handler stays a pure function of (context, arguments) from the
    # execution service's point of view, while still being able to prove
    # bounded-retry behavior deterministically in tests.
    assert isinstance(arguments, FlakyInput)
    attempt = _FLAKY_ATTEMPTS.get(context.tool_execution_id, 0) + 1
    _FLAKY_ATTEMPTS[context.tool_execution_id] = attempt
    if arguments.sleep_seconds:
        time.sleep(arguments.sleep_seconds)
    if attempt <= arguments.fail_attempts:
        raise ToolExecutionFailedError("Deterministic demo failure.")
    return FlakyOutput(attempts_before_success=attempt)


_FLAKY_ATTEMPTS: dict[str, int] = {}


FLAKY_TOOL = Tool(
    spec=ToolSpec(
        key="demo.flaky",
        display_name="Flaky (test) tool",
        description=(
            "Deterministically fails `fail_attempts` times before succeeding; can sleep to "
            "prove timeout enforcement. For platform verification only."
        ),
        input_model=FlakyInput,
        output_model=FlakyOutput,
        risk_level=RiskLevel.READ_ONLY,
        side_effect_type=SideEffectType.NONE,
        default_timeout_seconds=1.0,
        max_timeout_seconds=2.0,
        retry_policy=RetryPolicy(
            max_retries=3, retryable_error_codes=frozenset({"tool_execution_failed"})
        ),
        idempotency_mode=IdempotencyMode.SAFE,
    ),
    handler=_flaky_handler,
)


def register_demo_tools(target_registry) -> None:  # noqa: ANN001
    for tool in (ECHO_TOOL, ADD_TOOL, FLAKY_TOOL):
        if tool.spec.key not in target_registry:
            target_registry.register(tool)
