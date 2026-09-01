"""Agent configuration and bounded run-lifecycle services.

State transitions are never decided by serializer validation alone: every
transition here re-reads the row under ``select_for_update`` inside a
transaction and validates the *current* database state before writing,
which is what makes duplicate claims, racing cancellations, and terminal-state
reopening safe (see ``docs/adr`` and section 18/26 of the Phase 5 brief).
"""

from __future__ import annotations

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
from observability.tracing import domain_span, finalize_domain_span
from workspaces.models import Workspace

from .errors import (
    AgentRunNotCancellableError,
    AgentVersionNotPublishableError,
    AgentVersionNotPublishedError,
)
from .failure_classification import RecoveryAction, classify_terminal_failure
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
from .providers.schemas import LLMMessage, ToolDescriptor
from .runtime.budgets import Budgets
from .runtime.graph import (
    RunContext,
    new_run_context,
    resume_state_after_tool,
    run_graph,
    run_resume_graph,
)
from .tool_catalog import ToolCatalogConfigurationError, get_bound_tool_descriptors
from .tool_runtime import ToolResultContext, ToolResultStatus

logger = logging.getLogger("supportpilot")

MAX_INPUT_MESSAGE_CHARS = 8000

# Phase 9 Block 5 (section 23-25, 87): deterministic, server-owned
# acknowledgement text for a successful handoff. Never model-generated —
# a handoff never spends an extra model call merely to say a human will
# take over, and never promises a specific response time or staff member.
HANDOFF_ACKNOWLEDGEMENT_TEXT = (
    "I'm connecting you with a support specialist who can help with this — "
    "they'll follow up here."
)


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
    actor: User | None,
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
    from common.correlation import get_correlation_id

    from .tasks import execute_agent_run_task

    execute_agent_run_task.delay(str(run_id), correlation_id=get_correlation_id())


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
            from tools.models import ToolExecution, ToolExecutionStatus

            # ``select_related("tool_definition")`` so the metric label
            # captured below reuses the row already loaded for the cancel
            # call, rather than issuing a second query per execution.
            cancelled_at = timezone.now()
            cancelled_tool_observations: list[tuple[str, float | None]] = []
            for execution in locked.tool_executions.filter(
                status=ToolExecutionStatus.WAITING_FOR_APPROVAL
            ).select_related("tool_definition"):
                cancel_approval_for_execution(execution=execution, reason="run_cancelled")
                # Section 21, 130: a conditional UPDATE, not a blind
                # overwrite — a racing approve-resume may have already
                # claimed this exact row (WAITING_FOR_APPROVAL -> RUNNING,
                # possibly all the way to SUCCEEDED) between the queryset
                # above and here. This never clobbers that outcome back to
                # CANCELLED; it only cancels a row still genuinely waiting.
                updated = ToolExecution.objects.filter(
                    pk=execution.pk, status=ToolExecutionStatus.WAITING_FOR_APPROVAL
                ).update(
                    status=ToolExecutionStatus.CANCELLED,
                    completed_at=cancelled_at,
                    updated_at=cancelled_at,
                )
                if updated:
                    # Phase 11 Block 3 remediation: the ``cancelled``
                    # ToolExecution outcome — a plain queryset ``.update()``,
                    # not one of ``tools/execution.py``'s own locked
                    # terminal-transition functions, so it is recorded here
                    # instead. ``updated`` (the row-count the ``UPDATE``
                    # actually touched) is this row's own single-fire guard,
                    # mirroring ``approvals.services._terminate_execution`` —
                    # a racing approve-resume that already claimed the row
                    # observes nothing here.
                    duration_seconds = (
                        (cancelled_at - execution.started_at).total_seconds()
                        if execution.started_at is not None
                        else None
                    )
                    cancelled_tool_observations.append(
                        (execution.tool_definition.key, duration_seconds)
                    )
            if cancelled_tool_observations:
                _schedule_cancelled_tool_execution_observations(cancelled_tool_observations)
        # Section 113: a still-active human handoff for a now-cancelled run
        # becomes non-actionable too — imported locally to avoid a
        # module-level agents<->tickets import cycle, matching the approvals
        # import above.
        from tickets.services import cancel_handoffs_for_run

        cancel_handoffs_for_run(agent_run=locked, reason="run_cancelled")
        _schedule_agent_run_terminal_observation(
            locked, outcome="cancelled", terminal_at=locked.cancelled_at
        )
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
        from tools.errors import (
            ToolApprovalRequiredError,
            ToolBudgetExceededError,
            ToolError,
            ToolPolicyDeniedError,
        )
        from tools.execution import execute_tool as run_tool

        try:
            result = run_tool(
                agent_run=run,
                tool_key=tool_name,
                arguments=arguments,
                idempotency_key=idempotency_key,
                record_step=_record_step_factory(run),
            )
        except ToolApprovalRequiredError as exc:
            return {
                "approval_required": True,
                "error_code": exc.code,
                "error_message": exc.safe_message,
            }
        except ToolBudgetExceededError:
            return {"budget_exceeded": True, "budget_reason": "max_tool_calls_reached"}
        except ToolError as exc:
            terminal_codes = {
                "tool_configuration_error",
                "tool_invalid_output",
                "tool_idempotency_conflict",
                "tool_execution_in_progress",
                "tool_run_not_executable",
                "policy_evaluation_failed",
            }
            if exc.code in terminal_codes:
                return {
                    "terminal": True,
                    "error_code": exc.code,
                    "error_message": exc.safe_message,
                }
            status: ToolResultStatus = (
                "denied" if isinstance(exc, ToolPolicyDeniedError) else "failed"
            )
            result_context = ToolResultContext(
                tool_key=tool_name,
                status=status,
                error_code=exc.code,
            )
            return {
                "model_result": result_context.as_model_message(),
                "error_code": exc.code,
                "result_status": status,
            }
        result_context = ToolResultContext(
            tool_key=tool_name,
            status="succeeded",
            result=result.output,
            tool_execution_id=str(result.execution.id),
        )
        return {
            "model_result": result_context.as_model_message(),
            "tool_execution_id": str(result.execution.id),
            "result_status": "succeeded",
            "reused": result.reused,
        }

    return execute_tool


def _request_handoff_factory(run: AgentRun):
    """Bind a pure, stateless handoff-request validator to this run (Phase 9
    Block 5, section 5-12, 27-29, 68). Deliberately never writes a
    ``HumanHandoff`` row itself — see ``_complete_run_as_handoff``, which
    does that atomically with the run's own terminal transition so a
    racing cancellation can never see one materialize for an already-
    cancelled run (section 54).

    The model's proposed ``reason_code``/``summary`` are its only inputs;
    workspace, conversation, agent run, and ticket linkage are always
    read from this run's own trusted fields, never from provider output
    (section 7, 10-12, 30-32, 67).
    """

    def request_handoff(reason_code: str, summary: str) -> dict[str, Any]:
        from tickets.models import HumanHandoffReason

        if run.conversation_id is None:
            return {
                "ok": False,
                "error_code": "handoff_requires_conversation",
                "error_message": "This run has no conversation to hand off.",
            }
        code = (reason_code or "").strip()
        if code not in HumanHandoffReason.values:
            # Section 68: an unrecognized/spoofed reason code fails closed
            # rather than being silently remapped to a guessed value.
            return {
                "ok": False,
                "error_code": "invalid_handoff_reason",
                "error_message": "The requested handoff reason is not recognized.",
            }
        safe_summary = (summary or "").strip()
        if not safe_summary:
            return {
                "ok": False,
                "error_code": "invalid_handoff_summary",
                "error_message": "A handoff summary is required.",
            }
        return {"ok": True, "reason_code": code, "summary": safe_summary}

    return request_handoff


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
    tool_descriptors: tuple[ToolDescriptor, ...] | None = None,
    provider: Any | None = None,
) -> AgentRun:
    """Execute a run already claimed by the orchestration boundary.

    ``provider`` lets a caller substitute the LLM provider instance outright
    — used by the evaluation harness (``evaluations.services``) to inject a
    per-case ``DeterministicFakeLLMProvider`` scenario sequence without
    forking this orchestration path (section 13 of the Phase 12 brief).
    Every other caller omits it and gets the normal
    ``agent_version.provider``-driven resolution unchanged.
    """

    agent_version = run.agent_version
    if tool_descriptors is None:
        try:
            tool_descriptors = get_bound_tool_descriptors(
                agent_version=agent_version, workspace=run.workspace
            )
        except ToolCatalogConfigurationError as exc:
            return _fail_run(run, code=exc.code, message=exc.safe_message)
    if provider is None:
        try:
            provider = (
                get_llm_provider()
                if agent_version.provider == "fake"
                else _provider_for(agent_version)
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
        tool_descriptors=tool_descriptors,
        agent_run_id=str(run.id),
        is_cancelled=lambda: AgentRun.objects.filter(
            pk=run.pk, status=AgentRunStatus.CANCELLED
        ).exists(),
        request_handoff=_request_handoff_factory(run),
    )

    # Phase 11 Block 3 (section 15, 41-43): one domain span per orchestration
    # attempt, a parent of the ``llm.generate``/``tool.execute`` child spans
    # ``run_graph`` triggers via the ordinary current-span-context nesting —
    # no explicit parent wiring needed. Always ends within this synchronous
    # call, even when the outcome is WAITING_FOR_APPROVAL/HANDED_OFF (section
    # 42-43: never held open across the human-wait gap). Safe attributes
    # only: the run id (for trace/log correlation, never a Prometheus
    # label — section 15) and the bounded outcome; never the input message,
    # system prompt, or any model output.
    with domain_span(
        "agent.run", attributes={"supportpilot.agent_run_id": str(run.id)}
    ) as agent_span:
        try:
            result = run_graph(ctx, input_message=run.input_message)
        except Exception:  # pragma: no cover - defensive: never let an internal
            # exception escape the worker; fail the run instead.
            finalize_domain_span(agent_span, outcome="internal_error", is_error=True)
            logger.exception("agent_run_unexpected_failure", extra={"agent_run_id": str(run.id)})
            return _fail_run(
                run, code="agent_internal_error", message="The agent run failed unexpectedly."
            )

        if result.get("cancelled"):
            finalize_domain_span(agent_span, outcome="cancelled")
            return AgentRun.objects.get(pk=run.pk)
        if result.get("handoff_request"):
            finalize_domain_span(agent_span, outcome="handed_off")
            return _complete_run_as_handoff(run, result)
        if result.get("budget_exceeded"):
            finalize_domain_span(agent_span, outcome="budget_exceeded", is_error=True)
            return _budget_exceeded_run(
                run, reason=result.get("budget_exceeded_reason"), result=result
            )
        error_code = result.get("safe_error_code")
        if error_code == "approval_required":
            # Section 57-58: pause, never fail. Nothing here holds a worker
            # thread, Celery worker, or DB transaction open — the run simply
            # sits in WAITING_FOR_APPROVAL until a human decision dispatches
            # ``resume_approved_action_task`` (or the rejection/expiry path
            # marks it FAILED directly).
            finalize_domain_span(agent_span, outcome="waiting_for_approval")
            return _pause_run_for_approval(run, result)
        if error_code:
            finalize_domain_span(agent_span, outcome="failed", is_error=True)
            return _fail_or_handoff(run, error_code=error_code, result=result)
        finalize_domain_span(agent_span, outcome="succeeded")
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


# Phase 9 Block 4 (section 41-45, 127): the safe, model-visible outcome codes
# a resumed run's continuation may carry for a decision that never executes a
# handler. Deliberately not the tool's own error taxonomy — a rejected or
# expired action is a business/authorization outcome, not a tool failure.
_CONTINUATION_OUTCOME_CODES: dict[str, str] = {
    "rejected": "approval_rejected",
    "expired": "approval_expired",
}


def resume_agent_run_after_approval(approval_request_id: uuid.UUID | str) -> str:
    """Continue the run an approval decision (or its expiry) just resolved,
    from the exact paused tool-call boundary — never a new run, never a
    replay of the original customer request (section 4-6).

    * **Approved**: execute the one frozen ``ToolExecution`` the approval
      references, then feed its (untrusted, section 36) result to a bounded
      LLM follow-up.
    * **Rejected** / **Expired**: no handler is ever invoked; the LLM
      follow-up instead sees a safe, structured denial outcome (section
      41-47) — never the approver's private comment (section 43).
    * **Cancelled** (or anything else): the underlying run was already
      terminated by ``cancel_agent_run`` in the same transaction that
      cancelled this approval (section 50-51) — nothing to continue.

    Grant is single-use and single-action scoped (section 156-158): this
    function only ever touches the one ``ToolExecution`` the approval
    references, never any other tool call, run, or workspace. Safe to call
    more than once for the same ``approval_request_id`` (duplicate Celery
    delivery, section 24, 95) — the resume claim below is the single point
    of idempotency for *all* of these outcomes, not just the approved one.
    """
    from approvals.models import ApprovalRequest, ApprovalStatus
    from tools.errors import ToolError
    from tools.execution import resume_after_approval

    approval = ApprovalRequest.objects.select_related(
        "tool_execution",
        "tool_execution__agent_run",
        "tool_execution__agent_run__agent_version",
        "tool_execution__tool_definition",
    ).get(pk=approval_request_id)
    if approval.status not in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
    ):
        # PENDING (should never reach here) or CANCELLED — a cancelled
        # approval's run was already terminated, never resumed to the LLM
        # (section 51).
        return "skipped"

    run = approval.tool_execution.agent_run
    claimed = _claim_run_for_resume(run.pk)
    if claimed is None:
        return "already_resumed"
    run = claimed
    tool_key = approval.tool_execution.tool_definition.key
    record_step = _record_step_factory(run)

    if approval.status == ApprovalStatus.APPROVED:
        record_step(step_type=AgentStepType.APPROVAL_APPROVED, status=AgentStepStatus.SUCCEEDED)
        try:
            tool_result = resume_after_approval(
                tool_execution_id=str(approval.tool_execution_id), record_step=record_step
            )
        except ToolError as exc:
            return _fail_run(run, code=exc.code, message=exc.safe_message).status
        # Section 35-36, 60: the approved result is normalized through the
        # same safe, untrusted-data ``ToolResultContext`` wrapper the
        # ordinary ALLOW path uses — a human approving the *action* grants
        # it no special trust as *data* fed back to the model.
        tool_result_summary = ToolResultContext(
            tool_key=tool_key,
            status="succeeded",
            result=tool_result.output,
            tool_execution_id=str(approval.tool_execution_id),
        ).as_model_message()
    else:
        outcome = "rejected" if approval.status == ApprovalStatus.REJECTED else "expired"
        error_code = _CONTINUATION_OUTCOME_CODES[outcome]
        step_type = (
            AgentStepType.APPROVAL_REJECTED
            if outcome == "rejected"
            else AgentStepType.APPROVAL_EXPIRED
        )
        record_step(step_type=step_type, status=AgentStepStatus.SUCCEEDED)
        # No handler is ever invoked for a rejected/expired action (section
        # 41, 46-47, 58-59) — the LLM only ever sees a safe denial code,
        # never the approver's private comment (section 43, 76, 103).
        tool_result_summary = ToolResultContext(
            tool_key=tool_key, status="denied", error_code=error_code
        ).as_model_message()

    return _continue_run_after_resumed_tool(run, tool_result_summary=tool_result_summary).status


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
        request_handoff=_request_handoff_factory(run),
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

    # Phase 11 Block 3 (section 42): deliberately a *fresh* domain span, not
    # a child of the original ``agent.run`` span from before the
    # WAITING_FOR_APPROVAL pause — that span already ended (section 43), and
    # forcing a synchronous parent-child relationship across an
    # arbitrarily-long human approval wait would misrepresent the trace.
    # This span naturally parents under whatever *this* Celery task's own
    # trace context is (the approval decision's request, or the expiry
    # sweep) via ``common.tasks.CorrelatedTask``'s existing task span — the
    # stable link back to the original run is ``agent_run_id`` itself
    # (already present in every step/log/audit record for this run, section
    # 42's "stable domain IDs" choice), not span parentage.
    with domain_span(
        "agent.run.resume", attributes={"supportpilot.agent_run_id": str(run.id)}
    ) as agent_span:
        try:
            result = run_resume_graph(ctx, state=state)
        except Exception:  # pragma: no cover - defensive, mirrors execute_agent_run
            finalize_domain_span(agent_span, outcome="internal_error", is_error=True)
            logger.exception(
                "agent_run_resume_unexpected_failure", extra={"agent_run_id": str(run.id)}
            )
            return _fail_run(
                run, code="agent_internal_error", message="The agent run failed unexpectedly."
            )

        if result.get("handoff_request"):
            finalize_domain_span(agent_span, outcome="handed_off")
            return _complete_run_as_handoff(run, result)
        if result.get("budget_exceeded"):
            finalize_domain_span(agent_span, outcome="budget_exceeded", is_error=True)
            return _budget_exceeded_run(
                run, reason=result.get("budget_exceeded_reason"), result=result
            )
        error_code = result.get("safe_error_code")
        if error_code == "approval_required":
            # A second tool call in the same run also required approval — pause
            # again rather than fail (rare with the deterministic fake provider,
            # but the real graph already permits multi-turn tool use up to
            # max_tool_calls).
            finalize_domain_span(agent_span, outcome="waiting_for_approval")
            return _pause_run_for_approval(run, result)
        if error_code:
            finalize_domain_span(agent_span, outcome="failed", is_error=True)
            return _fail_or_handoff(run, error_code=error_code, result=result)
        finalize_domain_span(agent_span, outcome="succeeded")
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


def _schedule_agent_run_terminal_observation(
    run: AgentRun, *, outcome: str, terminal_at=None
) -> None:
    """Phase 11 Block 3 (section 12-14, 35-37): metrics for a committed
    AgentRun terminal transition are recorded only once the enclosing
    transaction actually commits — never inside the ``atomic()`` block
    itself, where a later rollback could otherwise leave a phantom count
    behind. Callers pass ``run`` already carrying its final terminal
    timestamp (set moments earlier in the same block) so duration is
    computed from values that are about to become durable, not re-read
    after the fact. ``terminal_at`` defaults to ``run.completed_at``;
    ``cancel_agent_run`` passes ``run.cancelled_at`` instead — the one
    terminal transition that uses a distinct timestamp field."""
    terminal_at = terminal_at if terminal_at is not None else run.completed_at
    duration_seconds = (
        (terminal_at - run.created_at).total_seconds() if terminal_at is not None else None
    )
    trigger = run.trigger
    run_id = str(run.id)

    def _record() -> None:
        from observability.metrics import observe_agent_run_terminal

        try:
            observe_agent_run_terminal(
                trigger=trigger, outcome=outcome, duration_seconds=duration_seconds
            )
        except Exception:  # noqa: BLE001 - telemetry must fail open
            logger.warning(
                "agent_run_metrics_recording_failed",
                extra={"event": "metrics_error", "agent_run_id": run_id},
            )

    transaction.on_commit(_record)


def _schedule_channel_response_routing(run: AgentRun) -> None:
    """Phase 13 (section 32, 39, 54): if this run's customer-visible reply
    originated from a channel that needs an external outbound delivery
    (currently: email), create the durable ``Delivery`` for it once the
    enclosing transaction commits — never inside the ``atomic()`` block
    itself, so a later rollback never creates a phantom delivery.

    Deliberately fail-open (mirrors ``_schedule_agent_run_terminal_observation``):
    a channel-routing failure must never surface as an agent-run failure —
    the run already succeeded/handed-off; only the *delivery* of its
    response is at stake here, and that has its own durable retry engine.
    Lazily imported to avoid a module-load-time dependency from ``agents``
    (a Phase 9 app) onto ``channel_ingress`` (Phase 13).
    """
    run_id = str(run.id)

    def _route() -> None:
        from channel_ingress.response_delivery import route_channel_response

        try:
            route_channel_response(run=run)
        except Exception:  # noqa: BLE001 - fail-open, see docstring
            logger.warning(
                "channel_response_routing_failed",
                extra={"event": "channel_response_routing_failed", "agent_run_id": run_id},
            )

    transaction.on_commit(_route)


def _schedule_cancelled_tool_execution_observations(
    observations: list[tuple[str, float | None]],
) -> None:
    """Phase 11 Block 3 remediation: mirrors
    ``_schedule_agent_run_terminal_observation`` for the ``ToolExecution``
    rows ``cancel_agent_run`` cancels directly via ``QuerySet.update()``
    (never routed through ``tools/execution.py``'s own terminal-transition
    helpers, so nothing else records this outcome). Deferred to
    ``transaction.on_commit`` so a rolled-back cancellation never leaves a
    phantom count behind, and the ``observe_tool_execution`` import stays
    local so tests can monkeypatch ``observability.metrics.
    observe_tool_execution`` and have it take effect here too. One failed
    observation must not skip the rest, and no observation may ever raise
    into the caller — telemetry fails open, never the committed
    cancellation."""

    def _record() -> None:
        from observability.metrics import observe_tool_execution

        for tool_name, duration_seconds in observations:
            try:
                observe_tool_execution(
                    tool_name=tool_name, outcome="cancelled", duration_seconds=duration_seconds
                )
            except Exception:  # noqa: BLE001 - telemetry must fail open
                logger.warning(
                    "tool_execution_metrics_recording_failed",
                    extra={"event": "metrics_error", "tool_name": tool_name},
                )

    transaction.on_commit(_record)


# ---------------------------------------------------------------------------
# Human handoff (Phase 9 Block 5, section 4, 13-27, 33-61)
# ---------------------------------------------------------------------------


def _fail_or_handoff(run: AgentRun, *, error_code: str, result: Mapping[str, Any]) -> AgentRun:
    """The single point where a terminal graph error is classified into
    FAIL or HANDOFF (section 33-40, 73-74) — never scattered ``if
    error_code == ...`` branching elsewhere."""
    action = classify_terminal_failure(
        error_code=error_code, has_conversation=run.conversation_id is not None
    )
    if action is RecoveryAction.HANDOFF:
        return _handoff_for_runtime_failure(run, error_code=error_code, result=result)
    return _fail_run(
        run,
        code=error_code,
        message=result.get("safe_error_message") or "The agent run failed.",
        result=result,
    )


def _handoff_for_runtime_failure(
    run: AgentRun, *, error_code: str, result: Mapping[str, Any]
) -> AgentRun:
    """Section 36, 46, 77: a bounded-retry-exhausted provider failure becomes
    a deterministic, server-owned handoff — never another LLM call to
    formulate it (section 87)."""
    from tickets.models import HumanHandoffReason

    validated = _request_handoff_factory(run)(
        HumanHandoffReason.RUNTIME_FAILURE,
        f"Automated recovery after repeated {error_code}.",
    )
    if not validated.get("ok"):  # pragma: no cover - defensive, e.g. no conversation
        return _fail_run(
            run,
            code=error_code,
            message=result.get("safe_error_message") or "The agent run failed.",
            result=result,
        )
    handoff_result = dict(result)
    handoff_result["handoff_request"] = {
        "reason_code": validated["reason_code"],
        "summary": validated["summary"],
    }
    return _complete_run_as_handoff(run, handoff_result)


def complete_run_via_existing_active_handoff(run: AgentRun) -> AgentRun:
    """Section 59-61: a conversation that already has an active handoff
    never starts autonomous execution for a new inbound message. No LLM
    call, no RAG retrieval, no budget consumed — the run is completed
    immediately, reusing (never duplicating, section 14-16) the
    conversation's existing active ``HumanHandoff``."""
    from tickets.models import HumanHandoffReason

    result: dict[str, Any] = {
        "model_call_count": run.model_call_count,
        "step_count": run.step_count,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "total_tokens": run.total_tokens,
        "estimated_cost_usd": (
            float(run.estimated_cost_usd) if run.estimated_cost_usd is not None else None
        ),
        "handoff_request": {
            "reason_code": HumanHandoffReason.CUSTOMER_REQUESTED,
            "summary": (
                "A new message arrived while this conversation was already "
                "awaiting a support specialist."
            ),
        },
    }
    return _complete_run_as_handoff(run, result)


def _complete_run_as_handoff(run: AgentRun, result: Mapping[str, Any]) -> AgentRun:
    """Create-or-reuse the ``HumanHandoff`` row and transition the run to
    ``HANDED_OFF`` atomically (section 54): both happen inside the same
    ``select_for_update`` block guarded by ``status == RUNNING``, so a
    racing cancellation that wins the row lock first leaves no orphaned
    active handoff behind — this function simply returns without ever
    calling ``create_or_reuse_handoff``."""
    from tickets.services import create_or_reuse_handoff

    request = result["handoff_request"]
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if locked.status != AgentRunStatus.RUNNING:
            return locked
        # Every caller (``_execute_handoff_request``'s validated request via
        # ``_request_handoff_factory``, and ``complete_run_via_existing_active_handoff``)
        # only ever reaches here for a run that already has a conversation.
        assert locked.conversation is not None
        handoff, created = create_or_reuse_handoff(
            workspace=locked.workspace,
            conversation=locked.conversation,
            reason_code=request["reason_code"],
            safe_summary=request["summary"],
            agent_run=locked,
            ticket=locked.ticket,
            request_id=locked.correlation_id or None,
        )
        _apply_usage(locked, result)
        locked.final_response = HANDOFF_ACKNOWLEDGEMENT_TEXT
        locked.status = AgentRunStatus.HANDED_OFF
        locked.completed_at = timezone.now()
        # Section 25-26, 56: reuses the exact same OneToOne idempotency
        # invariant as an ordinary successful completion — one acknowledgement
        # Message per run, guarded by the same lock and status check above.
        conversation = locked.conversation
        if conversation is not None and locked.output_message_id is None:
            from conversations.services import create_ai_agent_message

            message = create_ai_agent_message(
                workspace=locked.workspace,
                conversation=conversation,
                body=HANDOFF_ACKNOWLEDGEMENT_TEXT,
                metadata={"agent_run_id": str(locked.id), "handoff_id": str(handoff.id)},
            )
            locked.output_message = message
        locked.save()
        _next_sequence_and_create_step(
            locked,
            step_type=AgentStepType.RUN_HANDED_OFF,
            status=AgentStepStatus.SUCCEEDED,
            safe_metadata={"handoff_id": str(handoff.id), "reused": not created},
        )
        record_event(
            action=AuditAction.AGENT_RUN_HANDED_OFF,
            target_type="agent_run",
            target_id=locked.id,
            actor=locked.created_by,
            workspace=locked.workspace,
            metadata={"agent_run_id": str(locked.id), "handoff_id": str(handoff.id)},
            request_id=locked.correlation_id or None,
        )
        _schedule_agent_run_terminal_observation(locked, outcome="handed_off")
        _schedule_channel_response_routing(locked)
    return locked


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
        _schedule_agent_run_terminal_observation(locked, outcome="succeeded")
        _schedule_channel_response_routing(locked)
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
        _schedule_agent_run_terminal_observation(locked, outcome="failed")
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
        _schedule_agent_run_terminal_observation(locked, outcome="budget_exceeded")
    return locked
