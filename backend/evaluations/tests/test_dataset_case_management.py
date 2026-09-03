"""Dataset/case CRUD service and selector coverage (section 47-48)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from accounts.tests.factories import UserFactory
from workspaces.tests.factories import WorkspaceFactory

from .. import selectors, services
from ..models import EvaluationCaseStatus, EvaluationDatasetStatus
from .factories import EvaluationCaseFactory, EvaluationDatasetFactory


@pytest.mark.django_db
class TestDatasetCaseServices:
    def test_update_dataset(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace, name="Original")
        updated = services.update_evaluation_dataset(
            workspace=workspace,
            dataset=dataset,
            actor=UserFactory(),
            data={"name": "Renamed", "status": EvaluationDatasetStatus.ACTIVE},
        )
        assert updated.name == "Renamed"
        assert updated.status == EvaluationDatasetStatus.ACTIVE

    def test_create_case_rejects_invalid_expectations(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        with pytest.raises(ValidationError):
            services.create_evaluation_case(
                workspace=workspace,
                dataset=dataset,
                actor=UserFactory(),
                data={
                    "key": "bad-case",
                    "name": "Bad case",
                    "input_message": "hi",
                    "expectations": {"not_a_real_field": True},
                },
            )

    def test_update_case_disables_it(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        case = EvaluationCaseFactory(dataset=dataset)
        updated = services.update_evaluation_case(
            workspace=workspace,
            case=case,
            actor=UserFactory(),
            data={"status": EvaluationCaseStatus.DISABLED},
        )
        assert updated.status == EvaluationCaseStatus.DISABLED


@pytest.mark.django_db
class TestSelectors:
    def test_dataset_list_filters_by_status(self):
        workspace = WorkspaceFactory()
        EvaluationDatasetFactory(workspace=workspace, status=EvaluationDatasetStatus.DRAFT)
        EvaluationDatasetFactory(workspace=workspace, status=EvaluationDatasetStatus.ACTIVE)
        active_only = selectors.dataset_list_for_workspace(
            workspace=workspace, status=EvaluationDatasetStatus.ACTIVE
        )
        assert active_only.count() == 1

    def test_case_list_filters_by_status(self):
        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset, status=EvaluationCaseStatus.ACTIVE)
        EvaluationCaseFactory(dataset=dataset, status=EvaluationCaseStatus.DISABLED)
        active_only = selectors.case_list_for_dataset(
            workspace=workspace, dataset=dataset, status=EvaluationCaseStatus.ACTIVE
        )
        assert active_only.count() == 1

    def test_run_list_filters_by_dataset_id_and_rejects_malformed_id(self):
        from agents.tests.factories import PublishedAgentVersionFactory

        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        other_dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=other_dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()
        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )
        services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=other_dataset, agent_version=version
        )

        filtered = selectors.run_list_for_workspace(workspace=workspace, dataset_id=str(dataset.id))
        assert list(filtered) == [run]

        # Regression (Phase 14, Section 7): a malformed filter must fail
        # predictably, not be silently treated as "no matches".
        with pytest.raises(DRFValidationError):
            selectors.run_list_for_workspace(workspace=workspace, dataset_id="not-a-uuid")

    def test_result_list_filters_by_passed(self):
        from agents.tests.factories import PublishedAgentVersionFactory

        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()
        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        services.execute_evaluation_case(run.results.get().id)

        passed = selectors.result_list_for_run(workspace=workspace, run=run, passed=True)
        failed = selectors.result_list_for_run(workspace=workspace, run=run, passed=False)
        assert passed.count() == 1
        assert failed.count() == 0

    def test_failed_results_selector_excludes_passed(self):
        from agents.tests.factories import PublishedAgentVersionFactory

        workspace = WorkspaceFactory()
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        actor = UserFactory()
        run = services.start_evaluation_run(
            workspace=workspace, actor=actor, dataset=dataset, agent_version=version
        )
        services.claim_evaluation_run(run.id)
        services.execute_evaluation_case(run.results.get().id)

        assert selectors.failed_results_for_run(workspace=workspace, run=run).count() == 0
