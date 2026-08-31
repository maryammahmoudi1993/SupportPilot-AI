"""Evaluation dataset/case/run lifecycle services.

Every state transition re-reads the row under ``select_for_update`` inside a
transaction and validates the *current* database state before writing — the
same pattern ``agents/services.py`` uses for ``AgentRun`` (section 48, 20 of
the Phase 12 brief). Case execution reuses the real production agent
orchestration boundary (``agents.services.claim_agent_run`` /
``execute_claimed_agent_run``) unchanged — only the LLM provider instance is
substituted per case (section 13).
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from accounts.models import User
from agents import services as agent_services
from agents.models import (
    AgentRun,
    AgentRunStatus,
    AgentRunTrigger,
    AgentVersion,
    AgentVersionStatus,
)
from audit.models import AuditAction
from audit.services import record_event
from observability.metrics import (
    observe_evaluation_case_terminal,
    observe_evaluation_regression,
    observe_evaluation_run_terminal,
)
from observability.tracing import domain_span, finalize_domain_span
from workspaces.models import Workspace

from .errors import (
    EvaluationAgentVersionNotPublishedError,
    EvaluationDatasetHasNoActiveCasesError,
    EvaluationLiveProviderNotAllowedError,
    EvaluationResultNotReplayableError,
    EvaluationRunNotCancellableError,
    EvaluationRunsNotComparableError,
)
from .models import (
    EVALUATION_RESULT_TERMINAL_STATUSES,
    EVALUATION_RUN_TERMINAL_STATUSES,
    EvaluationCase,
    EvaluationCaseSnapshot,
    EvaluationCaseStatus,
    EvaluationDataset,
    EvaluationFailureCode,
    EvaluationResult,
    EvaluationResultStatus,
    EvaluationRun,
    EvaluationRunStatus,
)
from .providers import InvalidLLMScenarioError, build_fake_llm_provider
from .scoring import score_case

logger = logging.getLogger("supportpilot")


# ---------------------------------------------------------------------------
# Dataset / case management
# ---------------------------------------------------------------------------


def create_evaluation_dataset(
    *, workspace: Workspace, actor: User, data: dict[str, Any], request_id: str | None = None
) -> EvaluationDataset:
    with transaction.atomic():
        dataset = EvaluationDataset.objects.create(
            workspace=workspace,
            name=data["name"],
            description=data.get("description", ""),
            status=data.get("status", EvaluationDataset._meta.get_field("status").default),
            created_by=actor,
        )
        record_event(
            action=AuditAction.EVALUATION_DATASET_CREATED,
            target_type="evaluation_dataset",
            target_id=dataset.id,
            actor=actor,
            workspace=workspace,
            metadata={"dataset_id": str(dataset.id)},
            request_id=request_id,
        )
    return dataset


def update_evaluation_dataset(
    *,
    workspace: Workspace,
    dataset: EvaluationDataset,
    actor: User,
    data: dict[str, Any],
    request_id: str | None = None,
) -> EvaluationDataset:
    with transaction.atomic():
        for field in ("name", "description", "status"):
            if field in data:
                setattr(dataset, field, data[field])
        dataset.save()
        record_event(
            action=AuditAction.EVALUATION_DATASET_UPDATED,
            target_type="evaluation_dataset",
            target_id=dataset.id,
            actor=actor,
            workspace=workspace,
            metadata={"dataset_id": str(dataset.id)},
            request_id=request_id,
        )
    return dataset


def create_evaluation_case(
    *,
    workspace: Workspace,
    dataset: EvaluationDataset,
    actor: User,
    data: dict[str, Any],
    request_id: str | None = None,
) -> EvaluationCase:
    seeded_context = data.get("seeded_context", {})
    expectations = data.get("expectations", {})
    case = EvaluationCase(
        dataset=dataset,
        key=data["key"],
        name=data["name"],
        status=data.get("status", EvaluationCaseStatus.ACTIVE),
        input_message=data["input_message"],
        seeded_context=seeded_context,
        expectations=expectations,
        created_by=actor,
    )
    # ``clean()`` (not ``full_clean()``) — only the seeded_context/
    # expectations schema validation this app defines, matching how the
    # rest of the codebase does business validation explicitly rather than
    # via Django's blanket field-level full_clean() (which would also
    # reject e.g. created_by=None on fields declared null=True but not
    # blank=True).
    case.clean()
    with transaction.atomic():
        case.save()
        record_event(
            action=AuditAction.EVALUATION_CASE_CREATED,
            target_type="evaluation_case",
            target_id=case.id,
            actor=actor,
            workspace=workspace,
            metadata={"dataset_id": str(dataset.id), "case_id": str(case.id)},
            request_id=request_id,
        )
    return case


def update_evaluation_case(
    *,
    workspace: Workspace,
    case: EvaluationCase,
    actor: User,
    data: dict[str, Any],
    request_id: str | None = None,
) -> EvaluationCase:
    for field in ("name", "status", "input_message", "seeded_context", "expectations"):
        if field in data:
            setattr(case, field, data[field])
    # ``clean()`` (not ``full_clean()``) — only the seeded_context/
    # expectations schema validation this app defines, matching how the
    # rest of the codebase does business validation explicitly rather than
    # via Django's blanket field-level full_clean() (which would also
    # reject e.g. created_by=None on fields declared null=True but not
    # blank=True).
    case.clean()
    with transaction.atomic():
        case.save()
        record_event(
            action=AuditAction.EVALUATION_CASE_UPDATED,
            target_type="evaluation_case",
            target_id=case.id,
            actor=actor,
            workspace=workspace,
            metadata={"dataset_id": str(case.dataset_id), "case_id": str(case.id)},
            request_id=request_id,
        )
    return case


# ---------------------------------------------------------------------------
# Run creation (section 20-21, 39, 45)
# ---------------------------------------------------------------------------


def start_evaluation_run(
    *,
    workspace: Workspace,
    actor: User,
    dataset: EvaluationDataset,
    agent_version: AgentVersion,
    threshold_config: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> EvaluationRun:
    if agent_version.status != AgentVersionStatus.PUBLISHED:
        raise EvaluationAgentVersionNotPublishedError()

    active_cases = list(
        EvaluationCase.objects.filter(dataset=dataset, status=EvaluationCaseStatus.ACTIVE).order_by(
            "key"
        )
    )
    if not active_cases:
        raise EvaluationDatasetHasNoActiveCasesError()

    with transaction.atomic():
        run = EvaluationRun.objects.create(
            workspace=workspace,
            dataset=dataset,
            agent_version=agent_version,
            status=EvaluationRunStatus.PENDING,
            threshold_config=threshold_config or {},
            total_cases=len(active_cases),
            correlation_id=request_id or "",
            created_by=actor,
        )
        for sequence, case in enumerate(active_cases):
            snapshot = EvaluationCaseSnapshot.objects.create(
                run=run,
                case=case,
                sequence=sequence,
                case_key=case.key,
                name=case.name,
                input_message=case.input_message,
                seeded_context=case.seeded_context,
                expectations=case.expectations,
            )
            EvaluationResult.objects.create(
                run=run, case_snapshot=snapshot, status=EvaluationResultStatus.PENDING
            )
        record_event(
            action=AuditAction.EVALUATION_RUN_CREATED,
            target_type="evaluation_run",
            target_id=run.id,
            actor=actor,
            workspace=workspace,
            metadata={
                "run_id": str(run.id),
                "dataset_id": str(dataset.id),
                "case_count": len(active_cases),
            },
            request_id=request_id,
        )
        transaction.on_commit(lambda: _dispatch_start_run(run.id))
    return run


def _dispatch_start_run(run_id: uuid.UUID) -> None:
    from common.correlation import get_correlation_id

    from .tasks import start_evaluation_run_task

    start_evaluation_run_task.delay(str(run_id), correlation_id=get_correlation_id())


def claim_evaluation_run(run_id: uuid.UUID | str) -> EvaluationRun | None:
    """Atomically transition ``pending -> running``. Idempotent under Celery
    redelivery — returns ``None`` if another worker already claimed (or the
    run was already cancelled/terminated) (section 23-24)."""
    with transaction.atomic():
        run = EvaluationRun.objects.select_for_update().get(pk=run_id)
        if run.status != EvaluationRunStatus.PENDING:
            return None
        run.status = EvaluationRunStatus.RUNNING
        run.started_at = timezone.now()
        run.save()
    return run


def dispatch_pending_case_executions(run: EvaluationRun) -> None:
    """Dispatch one Celery task per still-``PENDING`` (non-replay) result of
    ``run``. Safe to call more than once — an already-claimed result simply
    no-ops when its task runs (section 22-24)."""
    result_ids = list(
        EvaluationResult.objects.filter(
            run=run, status=EvaluationResultStatus.PENDING, replay_of__isnull=True
        ).values_list("id", flat=True)
    )
    if not result_ids:
        return
    transaction.on_commit(lambda: _dispatch_case_executions(result_ids))


def _dispatch_case_executions(result_ids: list[uuid.UUID]) -> None:
    from common.correlation import get_correlation_id

    from .tasks import execute_evaluation_case_task

    correlation_id = get_correlation_id()
    for result_id in result_ids:
        execute_evaluation_case_task.delay(str(result_id), correlation_id=correlation_id)


# ---------------------------------------------------------------------------
# Case execution (section 13, 21-24, 25-27, 48)
# ---------------------------------------------------------------------------


def _claim_evaluation_result(result_id: uuid.UUID | str) -> EvaluationResult | None:
    with transaction.atomic():
        result = EvaluationResult.objects.select_for_update().get(pk=result_id)
        run = EvaluationRun.objects.select_for_update().get(pk=result.run_id)
        if result.status != EvaluationResultStatus.PENDING:
            return None
        if run.status == EvaluationRunStatus.CANCELLED or run.cancelled_at is not None:
            # Cancellation must prevent new claims (section 35).
            result.status = EvaluationResultStatus.CANCELLED
            result.completed_at = timezone.now()
            result.save()
            return None
        result.status = EvaluationResultStatus.RUNNING
        result.started_at = timezone.now()
        result.save()
    return result


def execute_evaluation_case(result_id: uuid.UUID | str) -> EvaluationResult:
    """Execute one evaluation case to a terminal ``EvaluationResult`` state.

    Safe to call more than once for the same ``result_id`` (Celery
    redelivery, section 23/59) — a result that is no longer ``PENDING`` is
    returned unchanged without re-executing."""
    claimed = _claim_evaluation_result(result_id)
    if claimed is None:
        result = EvaluationResult.objects.get(pk=result_id)
        return result

    snapshot = claimed.case_snapshot
    run = claimed.run

    if getattr(settings, "INTEGRATIONS_LIVE_PROVIDERS_ENABLED", False):
        # Fail closed (section 15) — never let an evaluation run reach a
        # live external provider because of an environment misconfiguration.
        return _terminate_result(
            claimed,
            failure_code=EvaluationFailureCode.PROVIDER_FAILURE,
            failure_message_safe=EvaluationLiveProviderNotAllowedError.safe_message,
        )

    with domain_span(
        "evaluation.case", attributes={"supportpilot.evaluation_result_id": str(claimed.id)}
    ) as span:
        try:
            fake_provider = build_fake_llm_provider(
                snapshot.seeded_context.get("llm_scenarios", [])
            )
        except InvalidLLMScenarioError as exc:
            finalize_domain_span(span, outcome="invalid_case", is_error=True)
            return _terminate_result(
                claimed,
                failure_code=EvaluationFailureCode.INVALID_CASE,
                failure_message_safe=str(exc),
            )

        agent_run = _create_evaluation_agent_run(run=run, snapshot=snapshot)
        agent_run = agent_services.claim_agent_run(agent_run.id)
        try:
            agent_run = agent_services.execute_claimed_agent_run(agent_run, provider=fake_provider)
        except Exception:  # noqa: BLE001 - a harness/provider failure, not a case assertion failure
            logger.exception(
                "evaluation_case_execution_failed", extra={"evaluation_result_id": str(claimed.id)}
            )
            finalize_domain_span(span, outcome="agent_execution_failed", is_error=True)
            return _terminate_result(
                claimed,
                failure_code=EvaluationFailureCode.AGENT_EXECUTION_FAILED,
                failure_message_safe="The agent run could not be executed.",
            )

        try:
            score = score_case(agent_run=agent_run, expectations=snapshot.expectations)
        except PydanticValidationError as exc:
            finalize_domain_span(span, outcome="invalid_case", is_error=True)
            return _terminate_result(
                claimed,
                failure_code=EvaluationFailureCode.INVALID_CASE,
                failure_message_safe=str(exc)[:500],
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "evaluation_scoring_failed", extra={"evaluation_result_id": str(claimed.id)}
            )
            finalize_domain_span(span, outcome="scoring_failed", is_error=True)
            return _terminate_result(
                claimed,
                failure_code=EvaluationFailureCode.SCORING_FAILED,
                failure_message_safe="Scoring could not be completed.",
            )

        finalize_domain_span(span, outcome="succeeded" if score.passed else "failed")

    with transaction.atomic():
        locked = EvaluationResult.objects.select_for_update().get(pk=claimed.pk)
        locked.status = EvaluationResultStatus.SUCCEEDED
        locked.agent_run = agent_run
        locked.scorer_output = score.output.model_dump(mode="json")
        locked.passed = score.passed
        locked.failure_code = score.failure_code
        locked.latency_ms = score.output.latency_ms
        locked.input_tokens = score.output.input_tokens
        locked.output_tokens = score.output.output_tokens
        locked.total_tokens = score.output.total_tokens
        locked.estimated_cost_usd = (
            Decimal(score.output.estimated_cost_usd) if score.output.estimated_cost_usd else None
        )
        locked.completed_at = timezone.now()
        locked.save()

    duration_seconds = _result_duration_seconds(locked)
    observe_evaluation_case_terminal(
        outcome="passed" if score.passed else "failed", duration_seconds=duration_seconds
    )
    _record_case_completion(run.id, locked)
    return locked


def _create_evaluation_agent_run(
    *, run: EvaluationRun, snapshot: EvaluationCaseSnapshot
) -> AgentRun:
    """Constructs the ``AgentRun`` row directly (mirroring
    ``agents.services.create_agent_run`` minus its automatic Celery
    dispatch) — evaluation execution is synchronous within its own task, and
    the LLM provider must be the per-case fake substituted by the caller,
    not whatever ``execute_agent_run_task`` would resolve by default."""
    return AgentRun.objects.create(
        workspace=run.workspace,
        agent_version=run.agent_version,
        trigger=AgentRunTrigger.EVALUATION,
        status=AgentRunStatus.PENDING,
        input_message=snapshot.input_message[: agent_services.MAX_INPUT_MESSAGE_CHARS],
        input_metadata={"evaluation_run_id": str(run.id), "evaluation_case_key": snapshot.case_key},
        correlation_id=run.correlation_id or "",
        created_by=run.created_by,
    )


def _terminate_result(
    result: EvaluationResult, *, failure_code: str, failure_message_safe: str
) -> EvaluationResult:
    with transaction.atomic():
        locked = EvaluationResult.objects.select_for_update().get(pk=result.pk)
        locked.status = EvaluationResultStatus.FAILED
        locked.passed = False
        locked.failure_code = failure_code
        locked.failure_message_safe = failure_message_safe[:500]
        locked.completed_at = timezone.now()
        locked.save()
    duration_seconds = _result_duration_seconds(locked)
    observe_evaluation_case_terminal(outcome="execution_failed", duration_seconds=duration_seconds)
    if result.replay_of_id is None:
        _record_case_completion(result.run_id, locked)
    return locked


def _result_duration_seconds(result: EvaluationResult) -> float | None:
    if result.started_at and result.completed_at:
        return max(0.0, (result.completed_at - result.started_at).total_seconds())
    return None


def _record_case_completion(run_id: uuid.UUID, result: EvaluationResult) -> None:
    """Updates the run's aggregate counters and finalizes it once every
    (non-replay) case has reached a terminal state (section 22, 24, 34).
    A replay's completion never touches these counters."""
    if result.replay_of_id is not None:
        return
    with transaction.atomic():
        run = EvaluationRun.objects.select_for_update().get(pk=run_id)
        run.completed_cases = EvaluationResult.objects.filter(
            run=run,
            replay_of__isnull=True,
            status__in=(EvaluationResultStatus.SUCCEEDED, EvaluationResultStatus.FAILED),
        ).count()
        run.passed_cases = EvaluationResult.objects.filter(
            run=run, replay_of__isnull=True, passed=True
        ).count()
        run.failed_cases = run.completed_cases - run.passed_cases
        run.save()
        should_finalize = (
            run.status == EvaluationRunStatus.RUNNING and run.completed_cases >= run.total_cases
        )
    if should_finalize:
        finalize_evaluation_run(run_id)


def finalize_evaluation_run(run_id: uuid.UUID | str) -> EvaluationRun | None:
    """Idempotent finalization (section 22, 34). Only transitions a
    currently-``RUNNING`` run whose completed-case count has caught up with
    its total — a duplicate call (two workers finishing the last two cases
    concurrently) simply no-ops on the second call."""
    with transaction.atomic():
        run = EvaluationRun.objects.select_for_update().get(pk=run_id)
        if run.status != EvaluationRunStatus.RUNNING:
            return None
        if run.completed_cases < run.total_cases:
            return None
        execution_failed = EvaluationResult.objects.filter(
            run=run, replay_of__isnull=True, status=EvaluationResultStatus.FAILED
        ).count()
        if run.total_cases > 0 and execution_failed == run.total_cases:
            run.status = EvaluationRunStatus.FAILED
        elif execution_failed > 0:
            run.status = EvaluationRunStatus.PARTIAL
        else:
            run.status = EvaluationRunStatus.SUCCEEDED
        run.completed_at = timezone.now()
        run.save()
        record_event(
            action=AuditAction.EVALUATION_RUN_COMPLETED,
            target_type="evaluation_run",
            target_id=run.id,
            actor=run.created_by,
            workspace=run.workspace,
            metadata={"run_id": str(run.id), "status": run.status},
            request_id=run.correlation_id or None,
        )
    observe_evaluation_run_terminal(outcome=run.status)
    return run


def cancel_evaluation_run(
    *, workspace: Workspace, run: EvaluationRun, actor: User, request_id: str | None = None
) -> EvaluationRun:
    with transaction.atomic():
        locked = EvaluationRun.objects.select_for_update().get(pk=run.pk)
        if locked.status in EVALUATION_RUN_TERMINAL_STATUSES:
            raise EvaluationRunNotCancellableError()
        # Any still-PENDING result is cancelled outright — never claimed by
        # a worker again (section 35). A RUNNING result is left alone; its
        # own claim already checked for cancellation and any about to start
        # will see it via ``_claim_evaluation_result``.
        cancelled_pending = EvaluationResult.objects.filter(
            run=locked, status=EvaluationResultStatus.PENDING, replay_of__isnull=True
        ).update(status=EvaluationResultStatus.CANCELLED, completed_at=timezone.now())
        locked.status = EvaluationRunStatus.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.completed_cases = EvaluationResult.objects.filter(
            run=locked,
            replay_of__isnull=True,
            status__in=(EvaluationResultStatus.SUCCEEDED, EvaluationResultStatus.FAILED),
        ).count()
        locked.passed_cases = EvaluationResult.objects.filter(
            run=locked, replay_of__isnull=True, passed=True
        ).count()
        locked.failed_cases = locked.completed_cases - locked.passed_cases
        locked.save()
        record_event(
            action=AuditAction.EVALUATION_RUN_CANCELLED,
            target_type="evaluation_run",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"run_id": str(locked.id), "cancelled_pending": cancelled_pending},
            request_id=request_id,
        )
    observe_evaluation_run_terminal(outcome="cancelled")
    return locked


# ---------------------------------------------------------------------------
# Replay (section 33)
# ---------------------------------------------------------------------------


def replay_evaluation_case(
    *,
    workspace: Workspace,
    actor: User,
    result: EvaluationResult,
    request_id: str | None = None,
) -> EvaluationResult:
    """Creates a NEW result referencing the same historical case snapshot —
    never mutates ``result`` (section 33). Replays always re-execute against
    the parent run's own ``agent_version`` (documented semantics); comparing
    a case against a *different* version is what ``start_evaluation_run`` +
    ``compare_evaluation_runs`` are for."""
    if result.status not in EVALUATION_RESULT_TERMINAL_STATUSES:
        raise EvaluationResultNotReplayableError()

    run = result.run
    if run.agent_version.status != AgentVersionStatus.PUBLISHED:
        raise EvaluationAgentVersionNotPublishedError()

    with transaction.atomic():
        replay = EvaluationResult.objects.create(
            run=run,
            case_snapshot=result.case_snapshot,
            status=EvaluationResultStatus.PENDING,
            replay_of=result,
        )
        record_event(
            action=AuditAction.EVALUATION_RESULT_REPLAYED,
            target_type="evaluation_result",
            target_id=replay.id,
            actor=actor,
            workspace=workspace,
            metadata={"replay_of": str(result.id), "run_id": str(run.id)},
            request_id=request_id,
        )
        transaction.on_commit(lambda: _dispatch_replay(replay.id))
    return replay


def _dispatch_replay(result_id: uuid.UUID) -> None:
    from common.correlation import get_correlation_id

    from .tasks import execute_evaluation_case_task

    execute_evaluation_case_task.delay(str(result_id), correlation_id=get_correlation_id())


# ---------------------------------------------------------------------------
# A/B comparison and regression gating (section 30-32)
# ---------------------------------------------------------------------------


def compare_evaluation_runs(
    *,
    workspace: Workspace,
    baseline_run: EvaluationRun,
    candidate_run: EvaluationRun,
    actor: User | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Paired, per-case comparison of two runs over the same dataset
    (section 30). Rejects comparison outright if the runs were not
    evaluated over the same case set (by ``case_key``) rather than silently
    comparing an incompatible subset."""
    baseline_keys = set(
        EvaluationCaseSnapshot.objects.filter(run=baseline_run).values_list("case_key", flat=True)
    )
    candidate_keys = set(
        EvaluationCaseSnapshot.objects.filter(run=candidate_run).values_list("case_key", flat=True)
    )
    if baseline_keys != candidate_keys:
        raise EvaluationRunsNotComparableError()

    baseline_metrics = _run_metrics(baseline_run)
    candidate_metrics = _run_metrics(candidate_run)
    deltas = {
        key: round(candidate_metrics[key] - baseline_metrics[key], 6) for key in baseline_metrics
    }

    threshold_config = candidate_run.threshold_config or {}
    threshold_results, regressions = _evaluate_thresholds(
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        deltas=deltas,
        threshold_config=threshold_config,
    )
    for category in regressions:
        observe_evaluation_regression(category=category)

    result = {
        "baseline_run_id": str(baseline_run.id),
        "candidate_run_id": str(candidate_run.id),
        "case_count": len(baseline_keys),
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "deltas": deltas,
        "thresholds": threshold_results,
        "regressions": sorted(regressions),
        "passed": not regressions,
    }
    record_event(
        action=AuditAction.EVALUATION_RUNS_COMPARED,
        target_type="evaluation_run",
        target_id=candidate_run.id,
        actor=actor,
        workspace=workspace,
        metadata={
            "baseline_run_id": str(baseline_run.id),
            "candidate_run_id": str(candidate_run.id),
            "passed": result["passed"],
        },
        request_id=request_id,
    )
    return result


def _run_metrics(run: EvaluationRun) -> dict[str, float]:
    results = list(EvaluationResult.objects.filter(run=run, replay_of__isnull=True))
    total = len(results) or 1
    pass_rate = sum(1 for r in results if r.passed) / total
    forbidden_violations = sum(
        1 for r in results if (r.scorer_output or {}).get("forbidden_tool_violation")
    )
    approval_violations = sum(
        1 for r in results if (r.scorer_output or {}).get("approval_violation")
    )
    handoff_rate = (
        sum(1 for r in results if (r.scorer_output or {}).get("handoff_occurred")) / total
    )
    return {
        "pass_rate": pass_rate,
        "forbidden_tool_violations": float(forbidden_violations),
        "approval_violations": float(approval_violations),
        "handoff_rate": handoff_rate,
    }


def _evaluate_thresholds(
    *,
    baseline_metrics: dict[str, float],
    candidate_metrics: dict[str, float],
    deltas: dict[str, float],
    threshold_config: dict[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    results: dict[str, Any] = {}
    regressions: set[str] = set()

    min_pass_rate = threshold_config.get("min_pass_rate")
    if min_pass_rate is not None:
        ok = candidate_metrics["pass_rate"] >= float(min_pass_rate)
        results["min_pass_rate"] = {"threshold": min_pass_rate, "passed": ok}
        if not ok:
            regressions.add("pass_rate")

    max_pass_rate_drop = threshold_config.get("max_pass_rate_drop")
    if max_pass_rate_drop is not None:
        ok = -deltas["pass_rate"] <= float(max_pass_rate_drop)
        results["max_pass_rate_drop"] = {"threshold": max_pass_rate_drop, "passed": ok}
        if not ok:
            regressions.add("pass_rate")

    if threshold_config.get("zero_forbidden_tool_violations"):
        ok = candidate_metrics["forbidden_tool_violations"] == 0
        results["zero_forbidden_tool_violations"] = {"threshold": True, "passed": ok}
        if not ok:
            regressions.add("forbidden_tool")

    if threshold_config.get("zero_approval_violations"):
        ok = candidate_metrics["approval_violations"] == 0
        results["zero_approval_violations"] = {"threshold": True, "passed": ok}
        if not ok:
            regressions.add("approval_compliance")

    max_handoff_rate_increase = threshold_config.get("max_handoff_rate_increase")
    if max_handoff_rate_increase is not None:
        ok = deltas["handoff_rate"] <= float(max_handoff_rate_increase)
        results["max_handoff_rate_increase"] = {
            "threshold": max_handoff_rate_increase,
            "passed": ok,
        }
        if not ok:
            regressions.add("handoff_rate")

    return results, regressions
