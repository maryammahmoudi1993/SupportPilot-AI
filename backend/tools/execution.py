"""The single controlled tool execution service (section 27 of the Phase 6
brief).

``execute_tool`` is the *only* path from a normalized tool request to a
handler invocation. It performs, in order: run-state validation, registry
resolution, binding/authorization checks, budget enforcement, typed input
validation, idempotency resolution, bounded timeout+retry execution, typed
output validation, redaction, and persistence. No other module invokes a
tool handler directly.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from agents.models import AgentRun, AgentRunStatus, AgentStepStatus, AgentStepType
from common.redaction import redact
from workspaces.models import Workspace

from .contracts import Tool, ToolExecutionContext
from .errors import (
    ToolBudgetExceededError,
    ToolConfigurationError,
    ToolDisabledError,
    ToolError,
    ToolExecutionFailedError,
    ToolExecutionInProgressError,
    ToolIdempotencyConflictError,
    ToolInvalidInputError,
    ToolInvalidOutputError,
    ToolNotBoundError,
    ToolRetryExhaustedError,
    ToolRunNotExecutableError,
    ToolTimeoutError,
)
from .idempotency import MAX_IDEMPOTENCY_KEY_LENGTH, fingerprint_arguments
from .models import ToolBinding, ToolDefinition, ToolExecution, ToolExecutionStatus
from .registry import registry as default_registry
from .selectors import resolve_enabled_binding

logger = logging.getLogger("supportpilot")

MAX_ARGUMENTS_BYTES = 8000
MAX_OUTPUT_BYTES = 16000
MIN_TIMEOUT_SECONDS = 1

StepRecorder = Callable[..., None]


@dataclass(frozen=True)
class ToolExecutionResult:
    execution: ToolExecution
    output: dict[str, Any] | None
    reused: bool


def execute_tool(
    *,
    agent_run: AgentRun,
    tool_key: str,
    arguments: dict[str, Any],
    idempotency_key: str | None = None,
    record_step: StepRecorder | None = None,
    tool_registry=None,
) -> ToolExecutionResult:
    tool_registry = tool_registry or default_registry
    workspace: Workspace = agent_run.workspace
    agent_version = agent_run.agent_version

    def _step(step_type: str, status: str, **kwargs: Any) -> None:
        if record_step is not None:
            record_step(step_type=step_type, status=status, **kwargs)

    _step(
        AgentStepType.TOOL_REQUESTED, AgentStepStatus.STARTED, safe_metadata={"tool_key": tool_key}
    )

    if agent_run.status != AgentRunStatus.RUNNING:
        raise ToolRunNotExecutableError()

    # 1. Registry resolution — the LLM cannot register or fuzzy-match a tool.
    tool = tool_registry.get(tool_key)  # raises ToolNotRegisteredError

    tool_definition = ToolDefinition.objects.filter(key=tool_key).first()
    if tool_definition is None:
        raise ToolConfigurationError("Tool is registered but not published to the catalog.")

    # 2. Binding / authorization — never derived from model arguments.
    binding = resolve_enabled_binding(agent_version=agent_version, tool_key=tool_key)
    if binding is None:
        any_binding = ToolBinding.objects.filter(
            agent_version=agent_version, tool_definition=tool_definition
        ).first()
        if any_binding is None:
            raise ToolNotBoundError()
        raise ToolDisabledError()

    # 3. Tool-call budget — bounded round-trips (section 41/43).
    if agent_run.tool_call_count >= agent_version.max_tool_calls:
        raise ToolBudgetExceededError()

    # 4. Input size + schema validation. The handler is never invoked on
    # invalid input (section 17, 74).
    if len(json.dumps(arguments, default=str)) > MAX_ARGUMENTS_BYTES:
        raise ToolInvalidInputError("Tool arguments payload is too large.")
    if idempotency_key and len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ToolInvalidInputError("Idempotency key is too long.")
    try:
        validated_arguments = tool.spec.input_model.model_validate(arguments)
    except PydanticValidationError as exc:
        _step(
            AgentStepType.TOOL_VALIDATION_FAILED,
            AgentStepStatus.FAILED,
            safe_metadata={"tool_key": tool_key},
            error_code="tool_invalid_input",
        )
        raise ToolInvalidInputError() from exc

    # 5. Effective timeout — the model can never widen it (section 36).
    effective_timeout = _effective_timeout(agent_run=agent_run, binding=binding, tool=tool)
    if effective_timeout is None:
        raise ToolBudgetExceededError("The run's remaining wall time is exhausted.")

    arguments_redacted = redact(
        validated_arguments.model_dump(mode="json"),
        extra_keys=frozenset(k.lower() for k in tool.spec.input_sensitive_fields),
    )
    fingerprint = fingerprint_arguments(validated_arguments.model_dump(mode="json"))

    # 6. Idempotency resolution + persistence claim.
    execution, should_execute, reused = _claim_execution(
        workspace=workspace,
        agent_run=agent_run,
        agent_version=agent_version,
        tool_definition=tool_definition,
        tool_binding=binding,
        idempotency_key=(idempotency_key or ""),
        fingerprint=fingerprint,
        arguments_redacted=arguments_redacted,
        timeout_seconds=max(MIN_TIMEOUT_SECONDS, round(effective_timeout)),
        tool=tool,
    )

    if reused:
        _step(
            AgentStepType.TOOL_IDEMPOTENCY_REUSED,
            AgentStepStatus.SUCCEEDED,
            safe_metadata={"tool_key": tool_key, "tool_execution_id": str(execution.id)},
        )
        return ToolExecutionResult(
            execution=execution, output=execution.result_redacted, reused=True
        )

    if not should_execute:  # pragma: no cover - defensive, unreachable in practice
        return ToolExecutionResult(
            execution=execution, output=execution.result_redacted, reused=False
        )

    _transition_running(execution)
    _step(
        AgentStepType.TOOL_EXECUTION_STARTED,
        AgentStepStatus.STARTED,
        safe_metadata={"tool_key": tool_key, "tool_execution_id": str(execution.id)},
    )

    context = ToolExecutionContext(
        workspace_id=str(workspace.id),
        tool_execution_id=str(execution.id),
        correlation_id=agent_run.correlation_id or None,
        deadline=timezone.now() + timedelta(seconds=effective_timeout),
        agent_run_id=str(agent_run.id),
        agent_version_id=str(agent_version.id),
        actor_user_id=str(agent_run.created_by_id) if agent_run.created_by_id else None,
    )

    try:
        output = _run_with_retries(
            execution=execution,
            tool=tool,
            context=context,
            arguments=validated_arguments,
            timeout_seconds=effective_timeout,
        )
    except ToolTimeoutError as exc:
        _finalize_failure(
            execution, status=ToolExecutionStatus.TIMED_OUT, code=exc.code, message=exc.safe_message
        )
        _increment_tool_call_count(agent_run)
        _step(
            AgentStepType.TOOL_EXECUTION_TIMED_OUT,
            AgentStepStatus.FAILED,
            error_code=exc.code,
            safe_metadata={"tool_key": tool_key, "tool_execution_id": str(execution.id)},
        )
        raise
    except ToolError as exc:
        _finalize_failure(
            execution, status=ToolExecutionStatus.FAILED, code=exc.code, message=exc.safe_message
        )
        _increment_tool_call_count(agent_run)
        _step(
            AgentStepType.TOOL_EXECUTION_FAILED,
            AgentStepStatus.FAILED,
            error_code=exc.code,
            safe_metadata={"tool_key": tool_key, "tool_execution_id": str(execution.id)},
        )
        raise

    _finalize_success(execution, output=output)
    _increment_tool_call_count(agent_run)
    _step(
        AgentStepType.TOOL_EXECUTION_SUCCEEDED,
        AgentStepStatus.SUCCEEDED,
        safe_metadata={
            "tool_key": tool_key,
            "tool_execution_id": str(execution.id),
            "attempt_count": execution.attempt_count,
        },
    )
    return ToolExecutionResult(execution=execution, output=output, reused=False)


# ---------------------------------------------------------------------------
# Timeout derivation
# ---------------------------------------------------------------------------


def _effective_timeout(*, agent_run: AgentRun, binding: ToolBinding, tool: Tool) -> float | None:
    configured = binding.configuration.get("timeout_seconds")
    candidate = float(configured) if configured else tool.spec.default_timeout_seconds
    effective = min(candidate, tool.spec.max_timeout_seconds)
    if agent_run.started_at is not None:
        elapsed = (timezone.now() - agent_run.started_at).total_seconds()
        remaining = agent_run.agent_version.wall_time_limit_seconds - elapsed
        if remaining <= 0:
            return None
        effective = min(effective, remaining)
    return effective


# ---------------------------------------------------------------------------
# Idempotency claim
# ---------------------------------------------------------------------------


def _claim_execution(
    *,
    workspace: Workspace,
    agent_run: AgentRun,
    agent_version,
    tool_definition: ToolDefinition,
    tool_binding: ToolBinding,
    idempotency_key: str,
    fingerprint: str,
    arguments_redacted: dict[str, Any],
    timeout_seconds: int,
    tool: Tool,
) -> tuple[ToolExecution, bool, bool]:
    with transaction.atomic():
        existing = None
        if idempotency_key:
            existing = (
                ToolExecution.objects.select_for_update()
                .filter(
                    workspace=workspace,
                    tool_definition=tool_definition,
                    idempotency_key=idempotency_key,
                )
                .first()
            )
        if existing is not None:
            return _resolve_existing(existing=existing, fingerprint=fingerprint, tool=tool)
        try:
            with transaction.atomic():
                execution = ToolExecution.objects.create(
                    workspace=workspace,
                    agent_run=agent_run,
                    agent_version=agent_version,
                    tool_definition=tool_definition,
                    tool_binding=tool_binding,
                    status=ToolExecutionStatus.PENDING,
                    idempotency_key=idempotency_key,
                    arguments_fingerprint=fingerprint if idempotency_key else "",
                    arguments_redacted=arguments_redacted,
                    timeout_seconds=timeout_seconds,
                )
            return execution, True, False
        except IntegrityError:
            # Lost a concurrent race for this idempotency key (section 65-66).
            existing = (
                ToolExecution.objects.select_for_update()
                .filter(
                    workspace=workspace,
                    tool_definition=tool_definition,
                    idempotency_key=idempotency_key,
                )
                .get()
            )
            return _resolve_existing(existing=existing, fingerprint=fingerprint, tool=tool)


def _resolve_existing(
    *, existing: ToolExecution, fingerprint: str, tool: Tool
) -> tuple[ToolExecution, bool, bool]:
    if existing.arguments_fingerprint != fingerprint:
        raise ToolIdempotencyConflictError()
    if existing.status in (ToolExecutionStatus.PENDING, ToolExecutionStatus.RUNNING):
        raise ToolExecutionInProgressError()
    if existing.status == ToolExecutionStatus.SUCCEEDED:
        return existing, False, True
    # Terminal failure/timeout/cancellation: the same idempotency key may be
    # retried (bounded by the tool's total attempt budget), rather than
    # permanently burning the key on a transient failure (section 77).
    if existing.attempt_count >= tool.spec.retry_policy.max_retries + 1:
        raise ToolRetryExhaustedError()
    existing.status = ToolExecutionStatus.PENDING
    existing.error_code = ""
    existing.error_message_safe = ""
    existing.completed_at = None
    existing.save(
        update_fields=["status", "error_code", "error_message_safe", "completed_at", "updated_at"]
    )
    return existing, True, False


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


def _transition_running(execution: ToolExecution) -> None:
    with transaction.atomic():
        locked = ToolExecution.objects.select_for_update().get(pk=execution.pk)
        if locked.status != ToolExecutionStatus.PENDING:
            raise ToolExecutionInProgressError()
        locked.status = ToolExecutionStatus.RUNNING
        locked.started_at = timezone.now()
        locked.save(update_fields=["status", "started_at", "updated_at"])
    execution.status = locked.status
    execution.started_at = locked.started_at


def _finalize_success(execution: ToolExecution, *, output: dict[str, Any]) -> None:
    with transaction.atomic():
        locked = ToolExecution.objects.select_for_update().get(pk=execution.pk)
        if locked.status != ToolExecutionStatus.RUNNING:
            return
        now = timezone.now()
        locked.status = ToolExecutionStatus.SUCCEEDED
        locked.result_redacted = output
        locked.completed_at = now
        locked.duration_ms = _duration_ms(locked.started_at, now)
        locked.save(
            update_fields=["status", "result_redacted", "completed_at", "duration_ms", "updated_at"]
        )
    execution.status = locked.status
    execution.result_redacted = locked.result_redacted


def _finalize_failure(execution: ToolExecution, *, status: str, code: str, message: str) -> None:
    with transaction.atomic():
        locked = ToolExecution.objects.select_for_update().get(pk=execution.pk)
        if locked.status != ToolExecutionStatus.RUNNING:
            return
        now = timezone.now()
        locked.status = status
        locked.error_code = code
        locked.error_message_safe = message
        locked.completed_at = now
        locked.duration_ms = _duration_ms(locked.started_at, now)
        locked.save(
            update_fields=[
                "status",
                "error_code",
                "error_message_safe",
                "completed_at",
                "duration_ms",
                "updated_at",
            ]
        )
    execution.status = locked.status


def _duration_ms(started_at, completed_at) -> int | None:
    if started_at is None:
        return None
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _increment_tool_call_count(agent_run: AgentRun) -> None:
    with transaction.atomic():
        AgentRun.objects.filter(pk=agent_run.pk).update(
            tool_call_count=agent_run.tool_call_count + 1
        )
    agent_run.tool_call_count += 1


# ---------------------------------------------------------------------------
# Bounded execution: retries + timeout
# ---------------------------------------------------------------------------


def _run_with_retries(
    *,
    execution: ToolExecution,
    tool: Tool,
    context: ToolExecutionContext,
    arguments: Any,
    timeout_seconds: float,
) -> dict[str, Any]:
    spec = tool.spec
    while True:
        if execution.attempt_count >= spec.retry_policy.max_retries + 1:
            raise ToolRetryExhaustedError()  # pragma: no cover - defensive, see _resolve_existing
        execution.attempt_count += 1
        ToolExecution.objects.filter(pk=execution.pk).update(attempt_count=execution.attempt_count)
        try:
            return _invoke_with_timeout(
                tool=tool, context=context, arguments=arguments, timeout_seconds=timeout_seconds
            )
        except ToolTimeoutError:
            # Timeouts are never auto-retried: the handler thread may still
            # be running, and blindly retrying a possibly-non-idempotent
            # side effect is unsafe (section 38).
            raise
        except ToolError as exc:
            is_retryable = exc.code in spec.retry_policy.retryable_error_codes
            attempts_remain = execution.attempt_count < spec.retry_policy.max_retries + 1
            if is_retryable and attempts_remain:
                continue
            if is_retryable and not attempts_remain:
                # Retry budget exhausted within this call — normalize to one
                # stable code (section 49, 120) rather than surfacing
                # whichever underlying error happened to occur last.
                raise ToolRetryExhaustedError() from exc
            raise  # non-retryable: surface the original error as-is


def _invoke_with_timeout(
    *, tool: Tool, context: ToolExecutionContext, arguments: Any, timeout_seconds: float
) -> dict[str, Any]:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(tool.handler, context=context, arguments=arguments)
        try:
            raw_result = future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            raise ToolTimeoutError() from None
    finally:
        # Never block here: Python cannot forcibly interrupt a running
        # thread. A timed-out handler may keep running to completion in the
        # background; this is a documented limitation (section 37), not a
        # forced-cancellation guarantee.
        pool.shutdown(wait=False)

    return _validate_output(tool=tool, raw_result=raw_result)


def _validate_output(*, tool: Tool, raw_result: Any) -> dict[str, Any]:
    output_model = tool.spec.output_model
    try:
        if isinstance(raw_result, output_model):
            validated = raw_result
        elif isinstance(raw_result, dict):
            validated = output_model.model_validate(raw_result)
        else:
            raise ToolInvalidOutputError()
    except PydanticValidationError as exc:
        raise ToolInvalidOutputError() from exc
    except ToolError:
        raise
    except Exception as exc:  # pragma: no cover - defensive, unexpected handler exception
        logger.exception("tool_handler_unexpected_error")
        raise ToolExecutionFailedError() from exc

    dumped = redact(
        validated.model_dump(mode="json"),
        extra_keys=frozenset(k.lower() for k in tool.spec.output_sensitive_fields),
    )
    if len(json.dumps(dumped, default=str)) > MAX_OUTPUT_BYTES:
        raise ToolInvalidOutputError("Tool output exceeds the maximum allowed size.")
    return cast(dict[str, Any], dumped)
