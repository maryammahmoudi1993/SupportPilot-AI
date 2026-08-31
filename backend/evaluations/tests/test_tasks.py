"""Celery task boundary tests (section 64) — thin delegation only."""

from __future__ import annotations

import pytest

from accounts.tests.factories import UserFactory
from agents.tests.factories import PublishedAgentVersionFactory
from workspaces.tests.factories import WorkspaceFactory

from .. import services
from ..models import EvaluationResultStatus, EvaluationRunStatus
from ..tasks import execute_evaluation_case_task, start_evaluation_run_task
from .factories import EvaluationCaseFactory, EvaluationDatasetFactory


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
