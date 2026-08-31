"""Covers on-commit Celery dispatch, remaining error paths, and comparison
threshold branches not exercised elsewhere."""

from __future__ import annotations

from unittest import mock

import pytest
from django.test import override_settings

from accounts.tests.factories import UserFactory
from agents.models import AgentVersionStatus
from agents.tests.factories import AgentVersionFactory, PublishedAgentVersionFactory
from workspaces.tests.factories import WorkspaceFactory

from .. import services
from ..errors import EvaluationAgentVersionNotPublishedError
from ..models import EvaluationFailureCode, EvaluationResultStatus
from .factories import EvaluationCaseFactory, EvaluationDatasetFactory


@pytest.mark.django_db
class TestDispatch:
    def test_start_run_dispatches_task_on_commit(self, django_capture_on_commit_callbacks):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)

        with mock.patch("evaluations.tasks.start_evaluation_run_task.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                run = services.start_evaluation_run(
                    workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
                )
            delay.assert_called_once()
            assert delay.call_args.args[0] == str(run.id)

    def test_dispatch_pending_case_executions_on_commit(self, django_capture_on_commit_callbacks):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )
        run = services.claim_evaluation_run(run.id)

        with mock.patch("evaluations.tasks.execute_evaluation_case_task.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                services.dispatch_pending_case_executions(run)
            delay.assert_called_once()

    def test_dispatch_pending_case_executions_noop_when_nothing_pending(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )
        run = services.claim_evaluation_run(run.id)
        services.execute_evaluation_case(run.results.get().id)
        # Nothing PENDING remains — dispatch is a safe no-op, no exception.
        services.dispatch_pending_case_executions(run)

    def test_replay_dispatches_on_commit(self, django_capture_on_commit_callbacks):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()
        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        result = services.execute_evaluation_case(run.results.get().id)

        with mock.patch("evaluations.tasks.execute_evaluation_case_task.delay") as delay:
            with django_capture_on_commit_callbacks(execute=True):
                services.replay_evaluation_case(workspace=workspace, actor=actor, result=result)
            delay.assert_called_once()


@pytest.mark.django_db
class TestUnpublishedAgentVersion:
    def test_start_run_rejects_unpublished_version(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        draft_version = AgentVersionFactory(
            agent_definition__workspace=workspace, status=AgentVersionStatus.DRAFT
        )
        with pytest.raises(EvaluationAgentVersionNotPublishedError):
            services.start_evaluation_run(
                workspace=workspace,
                actor=UserFactory(),
                dataset=dataset,
                agent_version=draft_version,
            )

    def test_replay_rejects_when_run_version_no_longer_published(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()
        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        result = services.execute_evaluation_case(run.results.get().id)

        version.status = AgentVersionStatus.RETIRED
        version.save()

        with pytest.raises(EvaluationAgentVersionNotPublishedError):
            services.replay_evaluation_case(workspace=workspace, actor=actor, result=result)


@pytest.mark.django_db
class TestLiveProviderFailClosed:
    def test_execute_case_fails_closed_when_live_providers_enabled(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace, actor=UserFactory(), dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        result_id = run.results.get().id

        with override_settings(INTEGRATIONS_LIVE_PROVIDERS_ENABLED=True):
            result = services.execute_evaluation_case(result_id)

        assert result.status == EvaluationResultStatus.FAILED
        assert result.failure_code == EvaluationFailureCode.PROVIDER_FAILURE


@pytest.mark.django_db
class TestComparisonThresholds:
    def _passing_run(self, *, workspace, dataset, actor, threshold_config=None):
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        run = services.start_evaluation_run(
            workspace=workspace,
            actor=actor,
            dataset=dataset,
            agent_version=version,
            threshold_config=threshold_config,
        )
        services.claim_evaluation_run(run.id)
        for result in run.results.filter(status=EvaluationResultStatus.PENDING):
            services.execute_evaluation_case(result.id)
        run.refresh_from_db()
        return run

    def test_max_pass_rate_drop_and_handoff_increase_thresholds(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset, key="c1")
        actor = UserFactory()

        baseline = self._passing_run(workspace=workspace, dataset=dataset, actor=actor)
        candidate = self._passing_run(
            workspace=workspace,
            dataset=dataset,
            actor=actor,
            threshold_config={"max_pass_rate_drop": 0.5, "max_handoff_rate_increase": 0.5},
        )

        comparison = services.compare_evaluation_runs(
            workspace=workspace, baseline_run=baseline, candidate_run=candidate, actor=actor
        )
        assert comparison["passed"] is True
        assert "max_pass_rate_drop" in comparison["thresholds"]
        assert "max_handoff_rate_increase" in comparison["thresholds"]
