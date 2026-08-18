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

from django.db import transaction
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
from .runtime.budgets import Budgets
from .runtime.graph import new_run_context, run_graph

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
    input_metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AgentRun:
    if agent_version.status != AgentVersionStatus.PUBLISHED:
        raise AgentVersionNotPublishedError()
    with transaction.atomic():
        run = AgentRun.objects.create(
            workspace=workspace,
            agent_version=agent_version,
            conversation=conversation,
            ticket=ticket,
            trigger=trigger,
            status=AgentRunStatus.PENDING,
            input_message=input_message[:MAX_INPUT_MESSAGE_CHARS],
            input_metadata=input_metadata or {},
            correlation_id=request_id or "",
            created_by=actor,
        )
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


def _complete_run(run: AgentRun, result: Mapping[str, Any]) -> AgentRun:
    with transaction.atomic():
        locked = AgentRun.objects.select_for_update().get(pk=run.pk)
        if locked.status != AgentRunStatus.RUNNING:
            return locked
        _apply_usage(locked, result)
        locked.final_response = result.get("final_response", "")
        locked.status = AgentRunStatus.SUCCEEDED
        locked.completed_at = timezone.now()
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
