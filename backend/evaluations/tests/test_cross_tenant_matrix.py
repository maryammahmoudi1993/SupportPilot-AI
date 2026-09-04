"""Cross-tenant IDOR and nested-IDOR matrix for the evaluations domain
(Phase 15 checkpoint 3, Part A). ``EvaluationCase``, ``EvaluationCaseSnapshot``,
and ``EvaluationResult`` all lack a direct ``workspace`` FK — reachable only
via ``dataset.workspace`` / ``run.workspace`` — and the compare endpoint
resolves two independent run ids in the same request, a natural mixed-
tenant-filter target."""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from agents.tests.factories import PublishedAgentVersionFactory
from common.tests.security_matrix import two_workspaces

from .factories import (
    EvaluationCaseFactory,
    EvaluationCaseSnapshotFactory,
    EvaluationDatasetFactory,
    EvaluationResultFactory,
    EvaluationRunFactory,
)

__all__ = ["two_workspaces"]


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _base(workspace_id) -> str:
    return f"/api/v1/workspaces/{workspace_id}/evaluations"


@pytest.mark.django_db
class TestEvaluationDatasetCrossTenant:
    def test_foreign_workspace_dataset_detail_is_404(self, two_workspaces):
        d = two_workspaces
        dataset = EvaluationDatasetFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/datasets/{dataset.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_dataset_patch_is_404_and_unchanged(self, two_workspaces):
        d = two_workspaces
        dataset = EvaluationDatasetFactory(workspace=d["workspace_a"], name="Original")
        response = _client(d["b_owner"].user).patch(
            f"{_base(d['workspace_b'].id)}/datasets/{dataset.id}/",
            {"name": "Hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        dataset.refresh_from_db()
        assert dataset.name == "Original"


@pytest.mark.django_db
class TestEvaluationCaseNestedIDOR:
    def test_case_from_a_foreign_workspace_dataset_is_404(self, two_workspaces):
        d = two_workspaces
        dataset_a = EvaluationDatasetFactory(workspace=d["workspace_a"])
        case_a = EvaluationCaseFactory(dataset=dataset_a)
        dataset_b = EvaluationDatasetFactory(workspace=d["workspace_b"])

        # own dataset id (B) + a real but foreign case id (A) -> 404
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/datasets/{dataset_b.id}/cases/{case_a.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_patching_a_foreign_case_through_own_dataset_id_is_404_and_unchanged(
        self, two_workspaces
    ):
        d = two_workspaces
        dataset_a = EvaluationDatasetFactory(workspace=d["workspace_a"])
        case_a = EvaluationCaseFactory(dataset=dataset_a, name="Original")
        dataset_b = EvaluationDatasetFactory(workspace=d["workspace_b"])

        response = _client(d["b_owner"].user).patch(
            f"{_base(d['workspace_b'].id)}/datasets/{dataset_b.id}/cases/{case_a.id}/",
            {"name": "Hijacked"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        case_a.refresh_from_db()
        assert case_a.name == "Original"


@pytest.mark.django_db
class TestEvaluationRunCrossTenant:
    def test_foreign_workspace_run_detail_is_404(self, two_workspaces):
        d = two_workspaces
        run = EvaluationRunFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/runs/{run.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_run_cancel_is_404_and_status_unchanged(self, two_workspaces):
        d = two_workspaces
        from evaluations.models import EvaluationRunStatus

        run = EvaluationRunFactory(workspace=d["workspace_a"], status=EvaluationRunStatus.RUNNING)
        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/runs/{run.id}/cancel/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        run.refresh_from_db()
        assert run.status == EvaluationRunStatus.RUNNING

    def test_creating_a_run_against_a_foreign_workspaces_agent_version_is_rejected(
        self, two_workspaces
    ):
        d = two_workspaces
        dataset = EvaluationDatasetFactory(workspace=d["workspace_b"])
        version_a = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_a"])

        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/runs/",
            {"dataset_id": str(dataset.id), "agent_version_id": str(version_a.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestEvaluationResultNestedIDORAndCompare:
    def test_result_from_a_foreign_workspace_run_is_404(self, two_workspaces):
        d = two_workspaces
        run_a = EvaluationRunFactory(workspace=d["workspace_a"])
        snapshot_a = EvaluationCaseSnapshotFactory(run=run_a)
        result_a = EvaluationResultFactory(case_snapshot=snapshot_a)
        run_b = EvaluationRunFactory(workspace=d["workspace_b"])

        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/runs/{run_b.id}/results/{result_a.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_replaying_a_foreign_workspace_result_is_404_and_no_new_result_created(
        self, two_workspaces
    ):
        d = two_workspaces
        from evaluations.models import EvaluationResult

        run_a = EvaluationRunFactory(workspace=d["workspace_a"])
        snapshot_a = EvaluationCaseSnapshotFactory(run=run_a)
        result_a = EvaluationResultFactory(case_snapshot=snapshot_a)
        run_b = EvaluationRunFactory(workspace=d["workspace_b"])
        count_before = EvaluationResult.objects.count()

        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/runs/{run_b.id}/results/{result_a.id}/replay/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert EvaluationResult.objects.count() == count_before

    def test_compare_with_one_foreign_run_id_is_404_never_a_cross_tenant_comparison(
        self, two_workspaces
    ):
        """Both run ids are resolved independently, workspace-scoped —
        mixing a real Workspace A run into a Workspace B compare request
        must 404, never silently compare across tenants."""
        d = two_workspaces
        run_a = EvaluationRunFactory(workspace=d["workspace_a"])
        run_b = EvaluationRunFactory(workspace=d["workspace_b"])

        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/compare/",
            {"baseline_run_id": str(run_b.id), "candidate_run_id": str(run_a.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestEvaluationRBAC:
    def test_viewer_can_view_but_not_manage_dataset(self, two_workspaces):
        d = two_workspaces
        dataset = EvaluationDatasetFactory(workspace=d["workspace_a"])
        ok = _client(d["a_viewer"].user).get(f"{_base(d['workspace_a'].id)}/datasets/{dataset.id}/")
        assert ok.status_code == status.HTTP_200_OK

        denied = _client(d["a_viewer"].user).patch(
            f"{_base(d['workspace_a'].id)}/datasets/{dataset.id}/",
            {"name": "x"},
            format="json",
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_support_agent_cannot_start_a_run(self, two_workspaces):
        d = two_workspaces
        dataset = EvaluationDatasetFactory(workspace=d["workspace_a"])
        version = PublishedAgentVersionFactory(agent_definition__workspace=d["workspace_a"])
        response = _client(d["a_agent"].user).post(
            f"{_base(d['workspace_a'].id)}/runs/",
            {"dataset_id": str(dataset.id), "agent_version_id": str(version.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
