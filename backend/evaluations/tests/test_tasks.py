"""Celery task boundary tests (section 64) — thin delegation only."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.tests.factories import UserFactory
from agents.tests.factories import PublishedAgentVersionFactory
from workspaces.tests.factories import WorkspaceFactory

from .. import services
from ..models import EvaluationResult, EvaluationResultStatus, EvaluationRun, EvaluationRunStatus
from ..tasks import (
    execute_evaluation_case_task,
    recover_stuck_evaluation_runs_task,
    start_evaluation_run_task,
)
from .factories import (
    EvaluationCaseFactory,
    EvaluationCaseSnapshotFactory,
    EvaluationDatasetFactory,
    EvaluationResultFactory,
    EvaluationRunFactory,
)


@pytest.mark.django_db
class TestEvaluationTasks:
    def test_start_run_task_claims_and_dispatches(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )

        status_value = start_evaluation_run_task(str(run.id))
        assert status_value == EvaluationRunStatus.RUNNING

        # Redelivery is a safe no-op — the run is no longer PENDING.
        assert start_evaluation_run_task(str(run.id)) is None

    def test_execute_case_task_delegates_to_service(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        result = run.results.get()

        status_value = execute_evaluation_case_task(str(result.id))
        assert status_value == EvaluationResultStatus.SUCCEEDED

        # Redelivery: a second task run for the same result returns the
        # already-terminal status unchanged, never re-executing.
        assert execute_evaluation_case_task(str(result.id)) == EvaluationResultStatus.SUCCEEDED


@pytest.mark.django_db
class TestRecoverStuckEvaluationRunsTask:
    """Celery Beat wrapper (Phase 17) — thin delegation only, see
    ``evaluations/tests/test_recovery.py`` for the actual recovery logic
    coverage."""

    def test_task_delegates_to_the_recovery_sweep(self):
        run = EvaluationRunFactory(status=EvaluationRunStatus.RUNNING, total_cases=1)
        snapshot = EvaluationCaseSnapshotFactory(run=run, sequence=0, case_key="case-0")
        result = EvaluationResultFactory(
            run=run, case_snapshot=snapshot, status=EvaluationResultStatus.RUNNING
        )
        stale = timezone.now() - timedelta(seconds=10_000)
        EvaluationResult.objects.filter(pk=result.pk).update(updated_at=stale)
        EvaluationRun.objects.filter(pk=run.pk).update(updated_at=stale)

        recovered = recover_stuck_evaluation_runs_task.apply().result

        assert recovered == 1
        result.refresh_from_db()
        assert result.status == EvaluationResultStatus.FAILED

    def test_task_is_a_thin_wrapper_with_no_recovery_logic_of_its_own(self):
        import inspect

        source = inspect.getsource(recover_stuck_evaluation_runs_task)
        assert "select_for_update" not in source
        assert "finalize_evaluation_run" not in source
