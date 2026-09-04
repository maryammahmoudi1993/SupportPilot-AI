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
from typing import Any, NoReturn, cast

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from agents.models import AgentRun, AgentRunStatus, AgentStepStatus, AgentStepType
from common.redaction import redact
from observability.tracing import domain_span, finalize_domain_span
from workspaces.models import Workspace

from .contracts import Tool, ToolExecutionContext
from .errors import (
    ToolApprovalActionChangedError,
    ToolApprovalCancelledError,
    ToolApprovalExpiredError,
    ToolApprovalRejectedError,
    ToolApprovalRequiredError,
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
    ToolPolicyDeniedError,
    ToolPolicyEvaluationFailedError,
    ToolRetryExhaustedError,
    ToolRunNotExecutableError,
    ToolTimeoutError,
)
from .idempotency import MAX_IDEMPOTENCY_KEY_LENGTH, fingerprint_arguments
from .models import (
    ToolBinding,
    ToolDefinition,
    ToolDefinitionStatus,
    ToolExecution,
    ToolExecutionStatus,
)
from .registry import registry as default_registry
from .selectors import resolve_enabled_binding

# Terminal statuses reached only through the Phase 8 policy gate (never
# through ordinary handler failure) — an idempotency-key retry against one
# of these replays the stored outcome rather than resetting to PENDING,
# because each already owns a one-to-one RiskAssessment/PolicyEvaluation
# (and, for approvals, ApprovalRequest) row that must never be recreated for
# the same ToolExecution (see tools/models.py's status docstring).
_POLICY_TERMINAL_STATUSES = frozenset(
    {ToolExecutionStatus.BLOCKED_BY_POLICY, ToolExecutionStatus.APPROVAL_TERMINATED}
)

_APPROVAL_TERMINATION_ERRORS: dict[str, type[ToolError]] = {
    "approval_rejected": ToolApprovalRejectedError,
    "approval_expired": ToolApprovalExpiredError,
    "approval_cancelled": ToolApprovalCancelledError,
}

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

    # 3. Tool-call budget — early, advisory fast-fail (section 41/43). Reads
    # the live DB count rather than trusting the caller's possibly-stale
    # in-memory ``agent_run``, so an already-exhausted budget is rejected
    # here with zero rows created — this is what keeps
    # ``test_budget_exhausted_blocks_before_any_execution_record`` true.
    #
    # This check is deliberately NOT the authoritative security boundary
    # for a *concurrent* boundary case (persisted count == max - 1, two
    # callers racing): both can observe the same live count here and both
    # pass. The actual hard ceiling is enforced by the single atomic
    # conditional reservation in ``_reserve_budget_slot``, called
    # immediately before the handler/provider is ever invoked (both in the
    # main path below and in ``resume_after_approval``) — never here,
    # since a policy-denied or still-pending-approval call must not
    # consume a budget slot at all (only a call whose handler is actually
    # about to run may consume one).
    live_tool_call_count = (
        AgentRun.objects.filter(pk=agent_run.pk).values_list("tool_call_count", flat=True).first()
    )
    if live_tool_call_count is not None:
        agent_run.tool_call_count = live_tool_call_count
    if agent_run.tool_call_count >= agent_version.max_tool_calls:
        raise ToolBudgetExceededError()

    # 4. Input size + schema validation. The handler is never invoked on
    # invalid input (section 17, 74).
    #
    # ``arguments`` is still a raw, untyped dict here (schema validation
    # happens below) — a pathologically deep-but-small nesting (e.g. ~1000
    # levels of a single-key dict fits well under MAX_ARGUMENTS_BYTES)
    # makes ``json.dumps`` itself raise ``RecursionError`` before this
    # size guard can reject it on length. That must fail the same safe,
    # closed way as an oversized payload — never as an unhandled
    # exception escaping the tool boundary (Phase 15 checkpoint 5, Part G).
    try:
        arguments_json_length = len(json.dumps(arguments, default=str))
    except RecursionError as exc:
        raise ToolInvalidInputError("Tool arguments payload is too large.") from exc
    if arguments_json_length > MAX_ARGUMENTS_BYTES:
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
        if execution.status == ToolExecutionStatus.SUCCEEDED:
            _step(
                AgentStepType.TOOL_IDEMPOTENCY_REUSED,
                AgentStepStatus.SUCCEEDED,
                safe_metadata={"tool_key": tool_key, "tool_execution_id": str(execution.id)},
            )
            return ToolExecutionResult(
                execution=execution, output=execution.result_redacted, reused=True
            )
        # A prior attempt with this exact idempotency key was already denied
        # or approval-terminated (section 10-11) — replay that outcome
        # rather than silently re-entering the policy gate for the same
        # ToolExecution row (see ``_POLICY_TERMINAL_STATUSES`` above).
        _raise_policy_terminal_outcome(execution)

    if execution.status == ToolExecutionStatus.WAITING_FOR_APPROVAL:
        # A retry (same idempotency key) against an action that already has
        # a pending approval — never a second RiskAssessment/PolicyEvaluation
        # /ApprovalRequest for the same execution (section 61).
        raise ToolApprovalRequiredError()

    if not should_execute:  # pragma: no cover - defensive, unreachable in practice
        return ToolExecutionResult(
            execution=execution, output=execution.result_redacted, reused=False
        )

    # 6.5. Deterministic risk assessment + policy evaluation (section 9,
    # 21-29). Model output is never authorization: everything the gate
    # inspects comes from the trusted ToolDefinition and the already
    # schema-validated arguments, never from a client-suppliable field.
    #
    # The gate runs at most once per ToolExecution row — its RiskAssessment/
    # PolicyEvaluation are OneToOneField to this row (section 24: immutable
    # snapshots, never recalculated in place). An ALLOW-decided row that
    # later failed at the *handler* level (an ordinary timeout/provider
    # error) and was idempotency-key-reset back to PENDING for a normal
    # Phase 6 retry must reuse that stored ALLOW rather than re-entering the
    # gate — only a row that has never been evaluated skips straight to
    # execution once this check confirms no evaluation exists yet.
    if not _already_policy_evaluated(execution):
        _run_policy_gate(
            execution=execution,
            tool=tool,
            tool_definition=tool_definition,
            agent_run=agent_run,
            validated_arguments=validated_arguments,
            step=_step,
        )

    _transition_running(execution)

    # Authoritative hard-ceiling reservation (section 35-37 of the Phase 15
    # brief): one conditional atomic UPDATE whose WHERE clause embeds the
    # budget predicate itself — never a separate read-then-check-then-write
    # sequence, which is exactly what a strict ceiling under concurrency
    # cannot tolerate. Placed here, immediately before the handler is ever
    # invoked, so the slot is reserved strictly before the external/tool
    # side effect — never discovered as over-budget only after the side
    # effect already happened. A policy-denied or still-pending-approval
    # call never reaches this line, so it never consumes a slot.
    if not _reserve_budget_slot(agent_run=agent_run, max_tool_calls=agent_version.max_tool_calls):
        _finalize_failure(
            execution,
            status=ToolExecutionStatus.FAILED,
            code=ToolBudgetExceededError.code,
            message="The run's tool-call budget was exhausted by a concurrent call.",
        )
        _step(
            AgentStepType.TOOL_EXECUTION_FAILED,
            AgentStepStatus.FAILED,
            error_code=ToolBudgetExceededError.code,
            safe_metadata={"tool_key": tool_key, "tool_execution_id": str(execution.id)},
        )
        raise ToolBudgetExceededError()

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

    # Phase 11 Block 3 (section 21): one tool execution span per handler
    # invocation, a child of whatever agent/LLM span is already current.
    # Safe attributes only — the tool's registered (bounded) name and the
    # execution id for trace/log correlation, never args/result payload.
    with domain_span(
        "tool.execute",
        attributes={"tool.name": tool_key, "supportpilot.tool_execution_id": str(execution.id)},
    ) as tool_span:
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
                execution,
                status=ToolExecutionStatus.TIMED_OUT,
                code=exc.code,
                message=exc.safe_message,
            )
            finalize_domain_span(tool_span, outcome=ToolExecutionStatus.TIMED_OUT, is_error=True)
            _step(
                AgentStepType.TOOL_EXECUTION_TIMED_OUT,
                AgentStepStatus.FAILED,
                error_code=exc.code,
                safe_metadata={"tool_key": tool_key, "tool_execution_id": str(execution.id)},
            )
            raise
        except ToolError as exc:
            _finalize_failure(
                execution,
                status=ToolExecutionStatus.FAILED,
                code=exc.code,
                message=exc.safe_message,
            )
            finalize_domain_span(tool_span, outcome=ToolExecutionStatus.FAILED, is_error=True)
            _step(
                AgentStepType.TOOL_EXECUTION_FAILED,
                AgentStepStatus.FAILED,
                error_code=exc.code,
                safe_metadata={"tool_key": tool_key, "tool_execution_id": str(execution.id)},
            )
            raise

        _finalize_success(execution, output=output)
        finalize_domain_span(tool_span, outcome=ToolExecutionStatus.SUCCEEDED)
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
    if existing.status == ToolExecutionStatus.WAITING_FOR_APPROVAL:
        # Caller handles this specially (re-raises approval_required) —
        # never re-enters the gate for a row that already has an
        # ApprovalRequest attached.
        return existing, False, False
    if existing.status in (ToolExecutionStatus.SUCCEEDED, *_POLICY_TERMINAL_STATUSES):
        # SUCCEEDED replays its stored result; the two policy-terminal
        # statuses replay their stored denial/rejection (section 10-11,
        # 24) — neither is eligible for the idempotency-key retry-reset
        # below, because both already own one-to-one policy-gate rows for
        # this exact ToolExecution.
        return existing, False, True
    # Ordinary terminal failure/timeout/cancellation: the same idempotency
    # key may be retried (bounded by the tool's total attempt budget),
    # rather than permanently burning the key on a transient failure
    # (section 77). This execution has never been through the policy gate
    # (or was cancelled before reaching it), so resetting it to PENDING is
    # safe — the gate runs fresh, exactly once, on the reset row.
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
        if locked.status not in (
            ToolExecutionStatus.PENDING,
            ToolExecutionStatus.WAITING_FOR_APPROVAL,
        ):
            raise ToolExecutionInProgressError()
        locked.status = ToolExecutionStatus.RUNNING
        locked.started_at = timezone.now()
        locked.save(update_fields=["status", "started_at", "updated_at"])
    execution.status = locked.status
    execution.started_at = locked.started_at


def _raise_policy_terminal_outcome(execution: ToolExecution) -> NoReturn:
    if execution.status == ToolExecutionStatus.BLOCKED_BY_POLICY:
        raise ToolPolicyDeniedError(execution.error_message_safe or None)
    error_cls = _APPROVAL_TERMINATION_ERRORS.get(execution.error_code)
    if error_cls is None:  # pragma: no cover - defensive, every write path sets a known code
        raise ToolApprovalRejectedError(execution.error_message_safe or None)
    raise error_cls(execution.error_message_safe or None)


# ---------------------------------------------------------------------------
# Phase 8: deterministic risk assessment + policy evaluation gate
# ---------------------------------------------------------------------------


def _already_policy_evaluated(execution: ToolExecution) -> bool:
    from policies.models import PolicyEvaluation

    return PolicyEvaluation.objects.filter(tool_execution=execution).exists()


def _run_policy_gate(
    *,
    execution: ToolExecution,
    tool: Tool,
    tool_definition: ToolDefinition,
    agent_run: AgentRun,
    validated_arguments: Any,
    step: StepRecorder,
) -> None:
    from approvals.services import create_or_reuse_approval_request
    from policies.errors import PolicyEvaluationFailedError
    from policies.evaluator import evaluate_policy, resolve_active_version
    from policies.models import PolicyEffect
    from policies.risk import assess_risk
    from policies.services import persist_policy_evaluation, persist_risk_assessment

    canonical_arguments = validated_arguments.model_dump(mode="json")
    risk = assess_risk(
        tool_key=tool.spec.key,
        base_risk=tool_definition.risk_level,
        side_effect_type=tool_definition.side_effect_type,
        arguments=canonical_arguments,
    )
    step(
        AgentStepType.RISK_ASSESSED,
        AgentStepStatus.SUCCEEDED,
        safe_metadata={"tool_key": tool.spec.key, "effective_risk": risk.effective_risk},
    )

    # Everything below is one atomic unit: the RiskAssessment/PolicyEvaluation
    # (/ApprovalRequest) rows and the execution's status transition either
    # all commit together or none do. This is what makes a crash between
    # "row persisted" and "status transitioned" impossible to observe — a
    # retry of the same idempotency key would otherwise find an orphaned
    # RiskAssessment already attached to a still-PENDING execution and fail
    # with an IntegrityError on the next attempt's OneToOneField create.
    #
    # Deliberately no exception is raised from inside the ``atomic()`` block
    # below: Django rolls back a block the moment any exception propagates
    # out of it, which would silently discard the very decision being
    # recorded. Every branch instead sets ``outcome``/``reason`` and falls
    # through normally so the block commits; the control-flow exception
    # (denied/approval-required/evaluation-failed) is raised only after
    # that commit has already happened.
    outcome = "allow"
    reason = ""
    with transaction.atomic():
        active_version = resolve_active_version(workspace=execution.workspace)
        try:
            decision = evaluate_policy(
                tool_key=tool.spec.key,
                risk=risk,
                arguments=canonical_arguments,
                active_version=active_version,
            )
        except PolicyEvaluationFailedError as exc:
            # Fail closed (section 27): an evaluation that cannot safely
            # complete is never treated as ALLOW.
            risk_row = persist_risk_assessment(execution=execution, risk=risk)
            persist_policy_evaluation(
                execution=execution,
                risk_assessment=risk_row,
                policy_version=None,
                decision=PolicyEffect.DENY,
                decision_code="policy_evaluation_failed",
                safe_reason=exc.safe_message,
                matched_rule_ids=[],
            )
            _transition_blocked_by_policy(execution, message=exc.safe_message)
            outcome, reason = "evaluation_failed", exc.safe_message
        else:
            risk_row = persist_risk_assessment(execution=execution, risk=risk)
            evaluation_row = persist_policy_evaluation(
                execution=execution,
                risk_assessment=risk_row,
                policy_version=decision.policy_version,
                decision=decision.decision,
                decision_code=decision.decision_code,
                safe_reason=decision.safe_reason,
                matched_rule_ids=decision.matched_rule_ids,
            )
            if decision.decision == PolicyEffect.ALLOW:
                outcome, reason = "allow", decision.safe_reason
            elif decision.decision == PolicyEffect.DENY:
                _transition_blocked_by_policy(execution, message=decision.safe_reason)
                outcome, reason = "deny", decision.safe_reason
            else:
                # REQUIRE_APPROVAL — the handler is never invoked (section 61).
                create_or_reuse_approval_request(
                    execution=execution,
                    agent_run=agent_run,
                    evaluation=evaluation_row,
                    risk_assessment=risk_row,
                    required_role=decision.required_role,
                    ttl_seconds=decision.approval_ttl_seconds,
                    canonical_arguments=canonical_arguments,
                    tool=tool,
                )
                _transition_waiting_for_approval(execution)
                outcome, reason = "require_approval", decision.safe_reason
    # transaction.atomic() committed here — outcome/reason now safe to act on.

    # Phase 11 Block 3 (section 22-23): recorded once per gate pass, after
    # the decision above has already committed — ``evaluation_failed``
    # persisted the same ``PolicyEffect.DENY`` the plain ``deny`` branch did
    # (fail-closed), so both observe as "deny", the actual bounded decision
    # value that was written to ``PolicyEvaluation``, never an invented
    # fourth category.
    from observability.metrics import observe_policy_decision

    observe_policy_decision(decision="deny" if outcome == "evaluation_failed" else outcome)

    if outcome == "allow":
        step(
            AgentStepType.POLICY_EVALUATED,
            AgentStepStatus.SUCCEEDED,
            safe_metadata={"tool_key": tool.spec.key, "decision": "allow"},
        )
        return
    if outcome == "evaluation_failed":
        step(
            AgentStepType.POLICY_EVALUATED,
            AgentStepStatus.FAILED,
            error_code="policy_evaluation_failed",
            safe_metadata={"tool_key": tool.spec.key},
        )
        raise ToolPolicyEvaluationFailedError(reason)
    if outcome == "deny":
        step(
            AgentStepType.POLICY_EVALUATED,
            AgentStepStatus.SUCCEEDED,
            safe_metadata={"tool_key": tool.spec.key, "decision": "deny"},
        )
        raise ToolPolicyDeniedError(reason)
    step(
        AgentStepType.POLICY_EVALUATED,
        AgentStepStatus.SUCCEEDED,
        safe_metadata={"tool_key": tool.spec.key, "decision": "require_approval"},
    )
    step(
        AgentStepType.APPROVAL_REQUESTED,
        AgentStepStatus.SUCCEEDED,
        safe_metadata={"tool_key": tool.spec.key},
    )
    raise ToolApprovalRequiredError(reason)


def _schedule_tool_execution_observation(execution: ToolExecution, *, outcome: str) -> None:
    """Phase 11 Block 3 (section 19-20, 35-37): the single place every
    ToolExecution terminal-transition metric/span is recorded from. Shared
    by ``_finalize_success``/``_finalize_failure`` (called from both
    ``execute_tool`` and ``resume_after_approval`` — the same guarded,
    single-fire DB transition either way) and
    ``_transition_blocked_by_policy``; ``approvals.services._terminate_execution``
    calls :func:`observability.metrics.observe_tool_execution` directly for
    the ``approval_terminated`` outcome (a plain queryset ``.update()``, not
    one of this module's own locked-transition functions). Recorded via
    ``transaction.on_commit`` — never inside the ``atomic()`` block itself —
    so a later rollback can never leave a phantom count."""
    duration_seconds = (
        (execution.completed_at - execution.started_at).total_seconds()
        if execution.started_at is not None and execution.completed_at is not None
        else None
    )
    tool_name = execution.tool_definition.key

    def _record() -> None:
        from observability.metrics import observe_tool_execution

        try:
            observe_tool_execution(
                tool_name=tool_name, outcome=outcome, duration_seconds=duration_seconds
            )
        except Exception:  # noqa: BLE001 - telemetry must fail open
            logger.warning(
                "tool_execution_metrics_recording_failed",
                extra={"event": "metrics_error", "tool_execution_id": str(execution.id)},
            )

    transaction.on_commit(_record)


def _transition_blocked_by_policy(execution: ToolExecution, *, message: str) -> None:
    with transaction.atomic():
        locked = ToolExecution.objects.select_for_update().get(pk=execution.pk)
        if locked.status != ToolExecutionStatus.PENDING:
            raise ToolExecutionInProgressError()  # pragma: no cover - defensive
        locked.status = ToolExecutionStatus.BLOCKED_BY_POLICY
        locked.error_code = "policy_action_denied"
        locked.error_message_safe = message[:500]
        locked.completed_at = timezone.now()
        locked.save(
            update_fields=[
                "status",
                "error_code",
                "error_message_safe",
                "completed_at",
                "updated_at",
            ]
        )
        _schedule_tool_execution_observation(locked, outcome="blocked_by_policy")
    execution.status = locked.status


def _transition_waiting_for_approval(execution: ToolExecution) -> None:
    with transaction.atomic():
        locked = ToolExecution.objects.select_for_update().get(pk=execution.pk)
        if locked.status != ToolExecutionStatus.PENDING:
            raise ToolExecutionInProgressError()  # pragma: no cover - defensive
        locked.status = ToolExecutionStatus.WAITING_FOR_APPROVAL
        locked.save(update_fields=["status", "updated_at"])
    execution.status = locked.status


# ---------------------------------------------------------------------------
# Phase 8: resume after an approved decision
# ---------------------------------------------------------------------------


def resume_after_approval(
    *, tool_execution_id: str, record_step: StepRecorder | None = None, tool_registry=None
) -> ToolExecutionResult:
    """Execute the handler for a ``ToolExecution`` whose approval was just
    granted. Called only from the approvals resume task/service — never from
    a tool handler, never from client input (section 62, 66-67, 127-128).

    Re-checks only the hard safety invariants that may have changed while
    waiting (binding still enabled, tool still registered) — the policy
    snapshot recorded at approval time remains authoritative for this exact
    approved action (section 62). Executes using the *stored* redacted
    argument snapshot, never fresh model-generated arguments (TOCTOU
    protection, section 54-55): no current approval-gated tool has a
    sensitive input field (see docs/architecture note), so the redacted
    snapshot equals the original canonical arguments; if a future tool did
    have one, ``model_validate`` below would fail closed on the redaction
    placeholder rather than silently using the wrong value.
    """
    tool_registry = tool_registry or default_registry

    def _step(step_type: str, status: str, **kwargs: Any) -> None:
        if record_step is not None:
            record_step(step_type=step_type, status=status, **kwargs)

    execution = ToolExecution.objects.select_related(
        "workspace",
        "agent_run",
        "agent_version",
        "tool_definition",
        "tool_binding",
        "approval_request",
    ).get(pk=tool_execution_id)

    claimed = _claim_resume(execution)
    if claimed is None:
        # Already resumed by a concurrent/redelivered call, or no longer
        # resumable (section 67, 128) — return current state, never a
        # second handler invocation.
        execution.refresh_from_db()
        if execution.status == ToolExecutionStatus.SUCCEEDED:
            return ToolExecutionResult(
                execution=execution, output=execution.result_redacted, reused=True
            )
        if execution.status == ToolExecutionStatus.RUNNING:
            # Phase 16 Part A, section 8: a genuine concurrent/redelivered
            # resume call observed the winning racer's claim (WAITING_FOR_
            # APPROVAL -> RUNNING) but that racer has not finished yet — this
            # is not a rejection, expiry, or policy denial, so it must never
            # be misreported as one (the ``error_cls is None`` defensive
            # fallback below would otherwise fabricate
            # ``ToolApprovalRejectedError`` for a call that was never
            # actually rejected, incorrectly failing the whole agent run).
            # Mirrors ``_resolve_existing``'s identical "another caller
            # already owns this row" signal for the first-execution path.
            raise ToolExecutionInProgressError()
        _raise_policy_terminal_outcome(execution)
    execution = claimed

    # Frozen-action verification (section 8-9, 94, 125-126): the approval
    # authorizes exactly the argument fingerprint recorded on the
    # ApprovalRequest at request time. A row that somehow reaches resume
    # with a different fingerprint (only reachable through direct DB
    # tampering — no application code path ever rewrites
    # ``arguments_fingerprint`` on a WAITING_FOR_APPROVAL row) is never
    # "repaired" or executed against a guessed value; it fails closed with
    # zero handler/provider calls.
    approval_request = getattr(execution, "approval_request", None)
    if (
        approval_request is not None
        and approval_request.arguments_fingerprint
        and approval_request.arguments_fingerprint != execution.arguments_fingerprint
    ):
        _finalize_failure(
            execution,
            status=ToolExecutionStatus.FAILED,
            code="approval_action_changed",
            message="The approved action no longer matches what was requested.",
        )
        raise ToolApprovalActionChangedError()

    tool = tool_registry.get(execution.tool_definition.key)
    if (
        not execution.tool_binding.enabled
        or execution.tool_definition.status != ToolDefinitionStatus.ACTIVE
    ):
        _finalize_failure(
            execution,
            status=ToolExecutionStatus.FAILED,
            code="tool_disabled",
            message="The tool was disabled while this action was awaiting approval.",
        )
        raise ToolDisabledError()

    try:
        validated_arguments = tool.spec.input_model.model_validate(execution.arguments_redacted)
    except PydanticValidationError as exc:
        _finalize_failure(
            execution,
            status=ToolExecutionStatus.FAILED,
            code="tool_invalid_input",
            message="The approved action's arguments could not be safely reconstructed.",
        )
        raise ToolInvalidInputError() from exc

    effective_timeout = min(tool.spec.default_timeout_seconds, tool.spec.max_timeout_seconds)
    context = ToolExecutionContext(
        workspace_id=str(execution.workspace_id),
        tool_execution_id=str(execution.id),
        correlation_id=execution.agent_run.correlation_id or None,
        deadline=timezone.now() + timedelta(seconds=effective_timeout),
        agent_run_id=str(execution.agent_run_id),
        agent_version_id=str(execution.agent_version_id),
        actor_user_id=(
            str(execution.agent_run.created_by_id) if execution.agent_run.created_by_id else None
        ),
    )

    # Same authoritative hard-ceiling reservation as the main execute_tool
    # path (section 35-37): the approval pause never itself consumed a
    # budget slot (a still-pending approval must not count against the
    # budget), so the slot is reserved here, strictly before the handler
    # runs, not at claim/creation time. ``_claim_resume`` above already
    # guarantees only one caller ever reaches this point for a given
    # ``ToolExecution`` (concurrent/redelivered resumes are rejected
    # earlier), so this only ever races a *different* tool call on the same
    # run — exactly the case this single atomic conditional UPDATE closes.
    if not _reserve_budget_slot(
        agent_run=execution.agent_run, max_tool_calls=execution.agent_version.max_tool_calls
    ):
        _finalize_failure(
            execution,
            status=ToolExecutionStatus.FAILED,
            code=ToolBudgetExceededError.code,
            message="The run's tool-call budget was exhausted by a concurrent call.",
        )
        raise ToolBudgetExceededError()

    _step(
        AgentStepType.EXECUTION_RESUMED,
        AgentStepStatus.STARTED,
        safe_metadata={"tool_execution_id": str(execution.id)},
    )

    # Phase 11 Block 3 (section 21): same ``tool.execute`` span as the
    # ordinary ``execute_tool`` path — a child of whatever this resume's own
    # task/domain span is (``agents.services._continue_run_after_resumed_tool``'s
    # ``agent.run.resume``), never a false parent back to the original
    # pre-approval trace (section 42).
    with domain_span(
        "tool.execute",
        attributes={
            "tool.name": execution.tool_definition.key,
            "supportpilot.tool_execution_id": str(execution.id),
        },
    ) as tool_span:
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
                execution,
                status=ToolExecutionStatus.TIMED_OUT,
                code=exc.code,
                message=exc.safe_message,
            )
            finalize_domain_span(tool_span, outcome=ToolExecutionStatus.TIMED_OUT, is_error=True)
            raise
        except ToolError as exc:
            _finalize_failure(
                execution,
                status=ToolExecutionStatus.FAILED,
                code=exc.code,
                message=exc.safe_message,
            )
            finalize_domain_span(tool_span, outcome=ToolExecutionStatus.FAILED, is_error=True)
            raise

        _finalize_success(execution, output=output)
        finalize_domain_span(tool_span, outcome=ToolExecutionStatus.SUCCEEDED)
        _step(
            AgentStepType.TOOL_EXECUTION_SUCCEEDED,
            AgentStepStatus.SUCCEEDED,
            safe_metadata={"tool_execution_id": str(execution.id)},
        )
        return ToolExecutionResult(execution=execution, output=output, reused=False)


def _claim_resume(execution: ToolExecution) -> ToolExecution | None:
    """Race-safe single-resume claim (section 67-68, 90-91): only the first
    caller for a given ``ToolExecution`` transitions it to RUNNING."""
    with transaction.atomic():
        locked = ToolExecution.objects.select_for_update().get(pk=execution.pk)
        if locked.status != ToolExecutionStatus.WAITING_FOR_APPROVAL:
            return None
        locked.status = ToolExecutionStatus.RUNNING
        locked.started_at = timezone.now()
        locked.save(update_fields=["status", "started_at", "updated_at"])
    return locked


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
        _schedule_tool_execution_observation(locked, outcome="succeeded")
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
        _schedule_tool_execution_observation(locked, outcome=status)
    execution.status = locked.status


def _duration_ms(started_at, completed_at) -> int | None:
    if started_at is None:
        return None
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _reserve_budget_slot(*, agent_run: AgentRun, max_tool_calls: int) -> bool:
    """Atomically reserve one tool-call budget slot: a single conditional
    ``UPDATE ... WHERE tool_call_count < max_tool_calls`` whose affected-row
    count *is* the reservation result (section 35-37 of the Phase 15
    security brief) — never a separate read, compare, and
    ``F("tool_call_count") + 1`` write, since splitting those into distinct
    operations is exactly what lets two concurrent callers both observe
    room for one more call and both proceed. Postgres evaluates a single
    UPDATE's WHERE clause and SET atomically per row, so at most one of two
    truly concurrent callers targeting the same run can ever have this
    return ``True`` for the same slot.

    Callers must call this immediately before invoking the tool
    handler/provider — never earlier (a policy-denied or
    still-pending-approval call must never consume a slot) and never
    later (that would let the side effect happen before the reservation
    is known to have succeeded)."""
    updated = AgentRun.objects.filter(pk=agent_run.pk, tool_call_count__lt=max_tool_calls).update(
        tool_call_count=F("tool_call_count") + 1
    )
    if updated:
        agent_run.refresh_from_db(fields=["tool_call_count"])
    return bool(updated)


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
