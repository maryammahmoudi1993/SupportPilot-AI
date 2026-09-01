"""Tenant-first selectors for every evaluation-owned resource.

Every lookup filters by ``workspace`` before resolving the object, and every
"get one" helper raises ``Http404`` on a miss so a cross-workspace UUID never
distinguishes "exists in another workspace" from "does not exist" (section
37).
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.http import Http404

from workspaces.models import Workspace

from .models import (
    EvaluationCase,
    EvaluationCaseSnapshot,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)


def dataset_list_for_workspace(
    *, workspace: Workspace, status: str | None = None
) -> QuerySet[EvaluationDataset]:
    queryset = EvaluationDataset.objects.filter(workspace=workspace)
    if status:
        queryset = queryset.filter(status=status)
    return queryset.order_by("-created_at")


def dataset_get_for_workspace_or_404(
    *, workspace: Workspace, dataset_id: UUID | str
) -> EvaluationDataset:
    dataset = EvaluationDataset.objects.filter(workspace=workspace, pk=dataset_id).first()
    if dataset is None:
        raise Http404("Evaluation dataset not found.")
    return dataset


def case_list_for_dataset(
    *, workspace: Workspace, dataset: EvaluationDataset, status: str | None = None
) -> QuerySet[EvaluationCase]:
    queryset = EvaluationCase.objects.filter(dataset=dataset, dataset__workspace=workspace)
    if status:
        queryset = queryset.filter(status=status)
    return queryset.order_by("key")


def case_get_for_workspace_or_404(
    *, workspace: Workspace, dataset: EvaluationDataset, case_id: UUID | str
) -> EvaluationCase:
    case = EvaluationCase.objects.filter(
        pk=case_id, dataset=dataset, dataset__workspace=workspace
    ).first()
    if case is None:
        raise Http404("Evaluation case not found.")
    return case


def run_list_for_workspace(
    *,
    workspace: Workspace,
    status: str | None = None,
    dataset_id: UUID | str | None = None,
) -> QuerySet[EvaluationRun]:
    queryset = EvaluationRun.objects.filter(workspace=workspace).select_related(
        "dataset", "agent_version", "agent_version__agent_definition"
    )
    if status:
        queryset = queryset.filter(status=status)
    if dataset_id:
        try:
            resolved_id = UUID(str(dataset_id))
        except ValueError:
            return queryset.none()
        queryset = queryset.filter(dataset_id=resolved_id)
    return queryset.order_by("-created_at")


def run_get_for_workspace_or_404(*, workspace: Workspace, run_id: UUID | str) -> EvaluationRun:
    run = (
        EvaluationRun.objects.filter(workspace=workspace, pk=run_id)
        .select_related("dataset", "agent_version", "agent_version__agent_definition")
        .first()
    )
    if run is None:
        raise Http404("Evaluation run not found.")
    return run


def result_list_for_run(
    *,
    workspace: Workspace,
    run: EvaluationRun,
    status: str | None = None,
    passed: bool | None = None,
) -> QuerySet[EvaluationResult]:
    queryset = EvaluationResult.objects.filter(run=run, run__workspace=workspace).select_related(
        "case_snapshot", "agent_run"
    )
    if status:
        queryset = queryset.filter(status=status)
    if passed is not None:
        queryset = queryset.filter(passed=passed)
    return queryset.order_by("case_snapshot__sequence")


def result_get_for_workspace_or_404(
    *, workspace: Workspace, run: EvaluationRun, result_id: UUID | str
) -> EvaluationResult:
    result = (
        EvaluationResult.objects.filter(pk=result_id, run=run, run__workspace=workspace)
        .select_related("case_snapshot", "agent_run")
        .first()
    )
    if result is None:
        raise Http404("Evaluation result not found.")
    return result


def failed_results_for_run(
    *, workspace: Workspace, run: EvaluationRun
) -> QuerySet[EvaluationResult]:
    """Bounded selector for the case-level triage view — results that
    finished without passing (failed status, or scored and not passed)."""
    return result_list_for_run(workspace=workspace, run=run).exclude(passed=True)


def snapshot_list_for_run(
    *, workspace: Workspace, run: EvaluationRun
) -> QuerySet[EvaluationCaseSnapshot]:
    return EvaluationCaseSnapshot.objects.filter(run=run, run__workspace=workspace).order_by(
        "sequence"
    )
