"""Agent configuration and bounded run-lifecycle services.

State transitions are never decided by serializer validation alone: every
transition here re-reads the row under ``select_for_update`` inside a
transaction and validates the *current* database state before writing,
which is what makes duplicate claims, racing cancellations, and terminal-state
reopening safe (see ``docs/adr`` and section 18/26 of the Phase 5 brief).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from workspaces.models import Workspace

from .errors import (
    AgentRunNotCancellableError,
    AgentVersionNotPublishableError,
    AgentVersionNotPublishedError,
)
from .models import (
    AGENT_RUN_TERMINAL_STATUSES,
    AgentDefinition,
    AgentRun,
    AgentRunStatus,
    AgentStep,
    AgentStepStatus,
    AgentStepType,
    AgentVersion,
    AgentVersionStatus,
)
from .providers.config import get_llm_provider
from .providers.errors import ProviderConfigurationError
from .providers.schemas import LLMMessage
from .runtime.budgets import Budgets
from .runtime.graph import (
    RunContext,
    new_run_context,
    resume_state_after_tool,
    run_graph,
    run_resume_graph,
)

logger = logging.getLogger("supportpilot")

MAX_INPUT_MESSAGE_CHARS = 8000


# ---------------------------------------------------------------------------
# Agent definition / version configuration
# ---------------------------------------------------------------------------


def create_agent_definition(
    *, workspace: Workspace, actor: User, data: dict[str, Any], request_id: str | None = None
) -> AgentDefinition:
    with transaction.atomic():
        definition = AgentDefinition.objects.create(
            workspace=workspace,
            name=data["name"],
            description=data.get("description", ""),
            created_by=actor,
        )
        record_event(
            action=AuditAction.AGENT_DEFINITION_CREATED,
            target_type="agent_definition",
            target_id=definition.id,
            actor=actor,
            workspace=workspace,
            metadata={"agent_id": str(definition.id)},
            request_id=request_id,
        )
    return definition


def update_agent_definition(
    *,
    workspace: Workspace,
    definition: AgentDefinition,
    actor: User,
    data: dict[str, Any],
    request_id: str | None = None,
) -> AgentDefinition:
    with transaction.atomic():
        for field in ("name", "description", "status"):
            if field in data:
                setattr(definition, field, data[field])
        definition.save()
        record_event(
            action=AuditAction.AGENT_DEFINITION_UPDATED,
            target_type="agent_definition",
            target_id=definition.id,
            actor=actor,
            workspace=workspace,
            metadata={"agent_id": str(definition.id)},
            request_id=request_id,
        )
    return definition


def create_agent_version(
    *,
    workspace: Workspace,
    agent_definition: AgentDefinition,
    actor: User,
    data: dict[str, Any],
    request_id: str | None = None,
) -> AgentVersion:
    with transaction.atomic():
        last = (
            AgentVersion.objects.select_for_update()
            .filter(agent_definition=agent_definition)
            .order_by("-version")
            .first()
        )
        next_version = (last.version + 1) if last else 1
        version = AgentVersion.objects.create(
            agent_definition=agent_definition,
            version=next_version,
            provider=data["provider"],
            model=data["model"],
            system_prompt=data.get("system_prompt", ""),
            temperature=data.get("temperature", 0.0),
            max_output_tokens=data.get("max_output_tokens", 512),
            max_model_calls=data.get("max_model_calls", 1),
            max_steps=data.get("max_steps", 20),
            wall_time_limit_seconds=data.get("wall_time_limit_seconds", 30),
            provider_timeout_seconds=data.get("provider_timeout_seconds", 30),
            max_total_tokens=data.get("max_total_tokens"),
            max_estimated_cost_usd=data.get("max_estimated_cost_usd"),
            max_retry_attempts=data.get("max_retry_attempts", 1),
            max_tool_calls=data.get("max_tool_calls", 3),
            runtime_config=data.get("runtime_config", {}),
            created_by=actor,
        )
        record_event(
            action=AuditAction.AGENT_VERSION_CREATED,
            target_type="agent_version",
            target_id=version.id,
            actor=actor,
            workspace=workspace,
            metadata={"agent_id": str(agent_definition.id), "version": version.version},
            request_id=request_id,
        )
    return version


def publish_agent_version(
    *, workspace: Workspace, version: AgentVersion, actor: User, request_id: str | None = None
) -> AgentVersion:
    with transaction.atomic():
        locked = AgentVersion.objects.select_for_update().get(pk=version.pk)
        if locked.status != AgentVersionStatus.DRAFT:
            raise AgentVersionNotPublishableError()
        locked.status = AgentVersionStatus.PUBLISHED
        locked.published_at = timezone.now()
        locked.save()
        record_event(
            action=AuditAction.AGENT_VERSION_PUBLISHED,
            target_type="agent_version",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"agent_id": str(locked.agent_definition_id), "version": locked.version},
            request_id=request_id,
        )
    return locked


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


def create_agent_run(
    *,
    workspace: Workspace,
    agent_version: AgentVersion,
    actor: User,
    input_message: str,
    trigger: str,
    conversation=None,
    ticket=None,
    trigger_message=None,
    input_metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AgentRun:
    """Create (or, for a ``trigger_message``-triggered run, idempotently
    reuse) an ``AgentRun``.

    Phase 9 (section 18-19, 110-111): a ``trigger_message`` makes "one
    logical AgentRun per triggering customer message" a database invariant
    (``AgentRun.trigger_message`` is a ``OneToOneField``), not just an
    application-level check. Two callers racing to start a run for the same
    message — an HTTP retry, a redelivered webhook, concurrent workers —
    resolve to exactly one created run; the loser returns the winner's row
    unchanged rather than raising or creating a second run.
    """
    if agent_version.status != AgentVersionStatus.PUBLISHED:
        raise AgentVersionNotPublishedError()
    with transaction.atomic():
        if trigger_message is not None:
            existing = (
                AgentRun.objects.select_for_update().filter(trigger_message=trigger_message).first()
            )
            if existing is not None:
                return existing
        try:
            with transaction.atomic():
                run = AgentRun.objects.create(
                    workspace=workspace,
                    agent_version=agent_version,
                    conversation=conversation,
                    ticket=ticket,
                    trigger_message=trigger_message,
                    trigger=trigger,
                    status=AgentRunStatus.PENDING,
                    input_message=input_message[:MAX_INPUT_MESSAGE_CHARS],
                    input_metadata=input_metadata or {},
                    correlation_id=request_id or "",
                    created_by=actor,
                )
        except IntegrityError:
            if trigger_message is None:  # pragma: no cover - defensive, unreachable
                raise
            # Lost a concurrent race for this trigger_message's one-run slot
            # (no existing row to lock before the create above).
            return AgentRun.objects.get(trigger_message=trigger_message)
        transaction.on_commit(lambda: _dispatch_run(run.id))
    return run


def _dispatch_run(run_id: uuid.UUID) -> None:
    from .tasks import execute_agent_run_task

    execute_agent_run_task.delay(str(run_id))


def claim_agent_run(run_id: uuid.UUID | str) -> AgentRun | None:
    """Atomically transition ``pending -> running``.

    Returns the claimed run, or ``None`` if another worker already claimed
    (or terminated) it — the idempotent-start guard described in section 26.
    """
    with transaction.atomic():
        run = AgentRun.objects.select_for_update().get(pk=run_id)
        if run.status != AgentRunStatus.PENDING:
            return None
        run.status = AgentRunStatus.RUNNING
        run.started_at = timezone.now()
        run.save()
        record_event(
            action=AuditAction.AGENT_RUN_STARTED,
            target_type="agent_run",
            target_id=run.id,
            actor=run.created_by,
            workspace=run.workspace,
            metadata={"agent_run_id": str(run.id)},
            request_id=run.correlation_id or None,
        )
    return run


def cancel_agent_run(
    *, workspace: Workspace, run: AgentRun, actor: User, request_id: str | None = None
) -> AgentRun:
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if locked.status in AGENT_RUN_TERMINAL_STATUSES:
            raise AgentRunNotCancellableError()
        was_waiting_for_approval = locked.status == AgentRunStatus.WAITING_FOR_APPROVAL
        locked.status = AgentRunStatus.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.save()
        _next_sequence_and_create_step(
            locked,
            step_type=AgentStepType.RUN_CANCELLED,
            status=AgentStepStatus.SUCCEEDED,
        )
        record_event(
            action=AuditAction.AGENT_RUN_CANCELLED,
            target_type="agent_run",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"agent_run_id": str(locked.id)},
            request_id=request_id,
        )
        if was_waiting_for_approval:
            # Section 46: a pending approval for a now-cancelled run becomes
            # non-actionable — never approvable/rejectable after the fact.
            # Imported locally (like the tools imports below) to avoid a
            # module-level agents<->tools/approvals import cycle.
            from approvals.services import cancel_approval_for_execution
            from tools.models import ToolExecutionStatus

            for execution in locked.tool_executions.filter(
                status=ToolExecutionStatus.WAITING_FOR_APPROVAL
            ):
                cancel_approval_for_execution(execution=execution, reason="run_cancelled")
                execution.status = ToolExecutionStatus.CANCELLED
                execution.completed_at = timezone.now()
                execution.save(update_fields=["status", "completed_at", "updated_at"])
        # Section 113: a still-active human handoff for a now-cancelled run
        # becomes non-actionable too — imported locally to avoid a
        # module-level agents<->tickets import cycle, matching the approvals
        # import above.
        from tickets.services import cancel_handoffs_for_run

        cancel_handoffs_for_run(agent_run=locked, reason="run_cancelled")
    return locked


def _next_sequence_and_create_step(run: AgentRun, **fields: Any) -> AgentStep:
    last = AgentStep.objects.filter(run=run).order_by("-sequence").first()
    sequence = (last.sequence + 1) if last else 1
    return AgentStep.objects.create(run=run, workspace=run.workspace, sequence=sequence, **fields)


def _record_step_factory(run: AgentRun):
    def record_step(*, step_type: str, status: str, **kwargs: Any) -> None:
        safe_metadata = kwargs.pop("safe_metadata", {}) or {}
        _next_sequence_and_create_step(
            run,
            step_type=step_type,
            status=status,
            provider=kwargs.get("provider", ""),
            model=kwargs.get("model", ""),
            input_summary=kwargs.get("input_summary", ""),
            output_summary=kwargs.get("output_summary", ""),
            latency_ms=kwargs.get("latency_ms"),
            error_code=kwargs.get("error_code", ""),
            safe_metadata=safe_metadata,
            started_at=timezone.now(),
            completed_at=timezone.now(),
        )

    return record_step


def record_agent_operational_step(
    *, run: AgentRun, event: str, safe_metadata: dict[str, Any]
) -> None:
    """Persist a safe orchestration event without storing prompt content."""
    _record_step_factory(run)(
        step_type=AgentStepType.REQUEST_NORMALIZED,
        status=AgentStepStatus.SUCCEEDED,
        safe_metadata={"event": event, **safe_metadata},
    )


def _execute_tool_factory(run: AgentRun):
    """Bind ``tools.execution.execute_tool`` to this run and normalize every
    ``ToolError`` into the safe outcome dict the graph expects — the
    runtime never sees a raw tool exception (section 27, 44-45)."""

    def execute_tool(tool_name: str, arguments: dict[str, Any], idempotency_key: str | None):
        from tools.errors import ToolError
        from tools.execution import execute_tool as run_tool

        try:
            result = run_tool(
                agent_run=run,
                tool_key=tool_name,
                arguments=arguments,
                idempotency_key=idempotency_key,
                record_step=_record_step_factory(run),
            )
        except ToolError as exc:
            return {"succeeded": False, "error_code": exc.code, "error_message": exc.safe_message}
        return {
            "succeeded": True,
            "output_summary": json.dumps(result.output, default=str)[:500],
        }

    return execute_tool


def _version_budgets(agent_version: AgentVersion) -> Budgets:
    return Budgets(
        max_model_calls=agent_version.max_model_calls,
        max_steps=agent_version.max_steps,
        wall_time_limit_seconds=agent_version.wall_time_limit_seconds,
        provider_timeout_seconds=agent_version.provider_timeout_seconds,
        max_total_tokens=agent_version.max_total_tokens,
        max_estimated_cost_usd=agent_version.max_estimated_cost_usd,
        max_retry_attempts=agent_version.max_retry_attempts,
    )


def execute_agent_run(run_id: uuid.UUID | str) -> AgentRun:
    """Claim and run a pending agent run to a terminal state.

    Safe to call more than once for the same ``run_id`` (e.g. Celery
    redelivery): a run that is no longer ``pending`` is returned unchanged
    without re-executing.
    """
    run = claim_agent_run(run_id)
    if run is None:
        return AgentRun.objects.get(pk=run_id)
    return execute_claimed_agent_run(run)


def execute_claimed_agent_run(
    run: AgentRun,
    *,
    initial_messages: tuple[LLMMessage, ...] | None = None,
    output_metadata: dict[str, Any] | None = None,
) -> AgentRun:
    """Execute a run already claimed by the orchestration boundary."""

    agent_version = run.agent_version
    try:
        provider = (
            get_llm_provider() if agent_version.provider == "fake" else _provider_for(agent_version)
        )
    except ProviderConfigurationError as exc:
        return _fail_run(run, code=exc.code, message=exc.safe_message)

    budgets = _version_budgets(agent_version)
    ctx = new_run_context(
        provider=provider,
        budgets=budgets,
        model=agent_version.model,
        temperature=agent_version.temperature,
        max_output_tokens=agent_version.max_output_tokens,
        system_prompt=agent_version.system_prompt,
        correlation_id=run.correlation_id or None,
        record_step=_record_step_factory(run),
        execute_tool=_execute_tool_factory(run),
        initial_messages=initial_messages,
    )

    try:
        result = run_graph(ctx, input_message=run.input_message)
    except Exception:  # pragma: no cover - defensive: never let an internal
        # exception escape the worker; fail the run instead.
        logger.exception("agent_run_unexpected_failure", extra={"agent_run_id": str(run.id)})
        return _fail_run(
            run, code="agent_internal_error", message="The agent run failed unexpectedly."
        )

    if result.get("budget_exceeded"):
        return _budget_exceeded_run(run, reason=result.get("budget_exceeded_reason"), result=result)
    error_code = result.get("safe_error_code")
    if error_code == "approval_required":
        # Section 57-58: pause, never fail. Nothing here holds a worker
        # thread, Celery worker, or DB transaction open — the run simply
        # sits in WAITING_FOR_APPROVAL until a human decision dispatches
        # ``resume_approved_action_task`` (or the rejection/expiry path
        # marks it FAILED directly).
        return _pause_run_for_approval(run, result)
    if error_code:
        return _fail_run(
            run,
            code=error_code,
            message=result.get("safe_error_message") or "The agent run failed.",
            result=result,
        )
    return _complete_run(run, result, output_metadata=output_metadata)


def fail_claimed_agent_run(*, run: AgentRun, code: str, message: str) -> AgentRun:
    """Fail a claimed run through the normal safe terminal transition."""
    return _fail_run(run, code=code, message=message)


def _pause_run_for_approval(run: AgentRun, result: Mapping[str, Any]) -> AgentRun:
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if locked.status != AgentRunStatus.RUNNING:
            return locked
        _apply_usage(locked, result)
        locked.status = AgentRunStatus.WAITING_FOR_APPROVAL
        locked.save()
        _next_sequence_and_create_step(
            locked,
            step_type=AgentStepType.RUN_WAITING_FOR_APPROVAL,
            status=AgentStepStatus.SUCCEEDED,
        )
    return locked


# ---------------------------------------------------------------------------
# Resume after an approval decision (section 62, 66-69, 156-158)
# ---------------------------------------------------------------------------


def _claim_run_for_resume(run_id) -> AgentRun | None:
    """Race-safe single-resume claim, mirroring ``claim_agent_run`` —
    exactly one caller transitions WAITING_FOR_APPROVAL -> RUNNING for a
    given run, so a redelivered Celery task never resumes twice
    (section 67-68)."""
    with transaction.atomic():
        run = AgentRun.objects.select_for_update().get(pk=run_id)
        if run.status != AgentRunStatus.WAITING_FOR_APPROVAL:
            return None
        run.status = AgentRunStatus.RUNNING
        run.save(update_fields=["status", "updated_at"])
    return run


def resume_agent_run_after_approval(approval_request_id: uuid.UUID | str) -> str:
    """Resume the exact paused tool action an approval just granted, then
    continue the run's bounded graph from where it left off.

    Grant is single-use and single-action scoped (section 156-158): this
    function only ever touches the one ``ToolExecution`` the approval
    references, never any other tool call, run, or workspace.
    """
    from approvals.models import ApprovalRequest, ApprovalStatus
    from tools.errors import ToolError
    from tools.execution import resume_after_approval

    approval = ApprovalRequest.objects.select_related(
        "tool_execution", "tool_execution__agent_run", "tool_execution__agent_run__agent_version"
    ).get(pk=approval_request_id)
    if approval.status != ApprovalStatus.APPROVED:
        # Rejected/expired/cancelled, or a race already handled elsewhere —
        # nothing to resume (section 92-93).
        return "skipped"

    run = approval.tool_execution.agent_run
    claimed = _claim_run_for_resume(run.pk)
    if claimed is None:
        return "already_resumed"
    run = claimed

    try:
        tool_result = resume_after_approval(
            tool_execution_id=str(approval.tool_execution_id),
            record_step=_record_step_factory(run),
        )
    except ToolError as exc:
        return _fail_run(run, code=exc.code, message=exc.safe_message).status

    outcome_summary = json.dumps(tool_result.output, default=str)[:500]
    return _continue_run_after_resumed_tool(run, tool_result_summary=outcome_summary).status


def _continue_run_after_resumed_tool(run: AgentRun, *, tool_result_summary: str) -> AgentRun:
    agent_version = run.agent_version
    try:
        provider = (
            get_llm_provider() if agent_version.provider == "fake" else _provider_for(agent_version)
        )
    except ProviderConfigurationError as exc:
        return _fail_run(run, code=exc.code, message=exc.safe_message)

    budgets = _version_budgets(agent_version)
    ctx: RunContext = new_run_context(
        provider=provider,
        budgets=budgets,
        model=agent_version.model,
        temperature=agent_version.temperature,
        max_output_tokens=agent_version.max_output_tokens,
        system_prompt=agent_version.system_prompt,
        correlation_id=run.correlation_id or None,
        record_step=_record_step_factory(run),
        execute_tool=_execute_tool_factory(run),
    )
    state = resume_state_after_tool(
        input_message=run.input_message,
        model_call_count=run.model_call_count,
        step_count=run.step_count,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        total_tokens=run.total_tokens,
        estimated_cost_usd=(
            float(run.estimated_cost_usd) if run.estimated_cost_usd is not None else None
        ),
        tool_result_summary=tool_result_summary,
    )

    try:
        result = run_resume_graph(ctx, state=state)
    except Exception:  # pragma: no cover - defensive, mirrors execute_agent_run
        logger.exception("agent_run_resume_unexpected_failure", extra={"agent_run_id": str(run.id)})
        return _fail_run(
            run, code="agent_internal_error", message="The agent run failed unexpectedly."
        )

    if result.get("budget_exceeded"):
        return _budget_exceeded_run(run, reason=result.get("budget_exceeded_reason"), result=result)
    error_code = result.get("safe_error_code")
    if error_code == "approval_required":
        # A second tool call in the same run also required approval — pause
        # again rather than fail (rare with the deterministic fake provider,
        # but the real graph already permits multi-turn tool use up to
        # max_tool_calls).
        return _pause_run_for_approval(run, result)
    if error_code:
        return _fail_run(
            run,
            code=error_code,
            message=result.get("safe_error_message") or "The agent run failed.",
            result=result,
        )
    return _complete_run(run, result)


def _provider_for(agent_version: AgentVersion):
    from django.conf import settings

    if getattr(settings, "AGENTS_LLM_PROVIDER", "fake") != agent_version.provider:
        # The active environment provider must match the version's declared
        # provider; a version cannot silently execute against a different
        # vendor than it was configured/tested for.
        raise ProviderConfigurationError(
            f"Agent version requires provider {agent_version.provider!r}, "
            "which is not the configured runtime provider."
        )
    return get_llm_provider()


def _apply_usage(run: AgentRun, result: Mapping[str, Any]) -> None:
    run.model_call_count = result.get("model_call_count", run.model_call_count)
    run.step_count = result.get("step_count", run.step_count)
    run.input_tokens = result.get("input_tokens", run.input_tokens)
    run.output_tokens = result.get("output_tokens", run.output_tokens)
    run.total_tokens = result.get("total_tokens", run.total_tokens)
    cost = result.get("estimated_cost_usd")
    run.estimated_cost_usd = Decimal(str(cost)) if cost is not None else None


def _complete_run(
    run: AgentRun,
    result: Mapping[str, Any],
    *,
    output_metadata: dict[str, Any] | None = None,
) -> AgentRun:
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if locked.status != AgentRunStatus.RUNNING:
            return locked
        _apply_usage(locked, result)
        locked.final_response = result.get("final_response", "")
        locked.status = AgentRunStatus.SUCCEEDED
        locked.completed_at = timezone.now()
        # Phase 9 (section 54-56): persist the customer-visible response as a
        # Conversation Message, not only on the run row. Guarded by the
        # ``status != RUNNING`` check above and the row lock: a worker retry
        # that re-enters this function for an already-SUCCEEDED run returns
        # early without creating a second message, and
        # ``AgentRun.output_message`` (a OneToOneField) makes "at most one
        # final message per run" a database invariant on top of that.
        conversation = locked.conversation
        if conversation is not None and locked.final_response and locked.output_message_id is None:
            from conversations.services import create_ai_agent_message

            message = create_ai_agent_message(
                workspace=locked.workspace,
                conversation=conversation,
                body=locked.final_response,
                metadata={"agent_run_id": str(locked.id), **(output_metadata or {})},
            )
            locked.output_message = message
        locked.save()
        record_event(
            action=AuditAction.AGENT_RUN_COMPLETED,
            target_type="agent_run",
            target_id=locked.id,
            actor=locked.created_by,
            workspace=locked.workspace,
            metadata={"agent_run_id": str(locked.id)},
            request_id=locked.correlation_id or None,
        )
    return locked


def _fail_run(
    run: AgentRun, *, code: str, message: str, result: Mapping[str, Any] | None = None
) -> AgentRun:
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if locked.status in AGENT_RUN_TERMINAL_STATUSES:
            return locked
        if result:
            _apply_usage(locked, result)
        locked.status = AgentRunStatus.FAILED
        locked.failure_code = code
        locked.failure_message_safe = message
        locked.completed_at = timezone.now()
        locked.save()
        record_event(
            action=AuditAction.AGENT_RUN_FAILED,
            target_type="agent_run",
            target_id=locked.id,
            actor=locked.created_by,
            workspace=locked.workspace,
            metadata={"agent_run_id": str(locked.id), "failure_code": code},
            request_id=locked.correlation_id or None,
        )
    return locked


def _budget_exceeded_run(
    run: AgentRun, *, reason: str | None, result: Mapping[str, Any]
) -> AgentRun:
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if locked.status in AGENT_RUN_TERMINAL_STATUSES:
            return locked
        _apply_usage(locked, result)
        locked.status = AgentRunStatus.BUDGET_EXCEEDED
        locked.failure_code = f"budget_exceeded:{reason or 'unknown'}"
        locked.failure_message_safe = "The run exceeded its configured execution budget."
        locked.completed_at = timezone.now()
        locked.save()
        record_event(
            action=AuditAction.AGENT_RUN_FAILED,
            target_type="agent_run",
            target_id=locked.id,
            actor=locked.created_by,
            workspace=locked.workspace,
            metadata={"agent_run_id": str(locked.id), "failure_code": locked.failure_code},
            request_id=locked.correlation_id or None,
        )
    return locked
