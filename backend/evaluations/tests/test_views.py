"""API, RBAC, and tenant-isolation tests (section 36-38, 61-62)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from agents.tests.factories import PublishedAgentVersionFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .. import services
from .factories import EvaluationCaseFactory, EvaluationDatasetFactory


def _client(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace):
    return f"/api/v1/workspaces/{workspace.id}/evaluations"


@pytest.mark.django_db
class TestDatasetApi:
    def test_anonymous_is_401_and_foreign_workspace_is_404(self):
        workspace = WorkspaceFactory()
        assert _client().get(f"{_base(workspace)}/datasets/").status_code == 401
        membership = WorkspaceMembershipFactory()
        assert _client(membership.user).get(f"{_base(workspace)}/datasets/").status_code == 404

    @pytest.mark.parametrize(
        "role,allowed",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, True),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_manage_rbac_and_every_role_can_read(self, role, allowed):
        membership = WorkspaceMembershipFactory(role=role)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/datasets/", {"name": "Golden set"}, format="json"
        )
        assert response.status_code == (201 if allowed else 403)
        assert (
            _client(membership.user).get(f"{_base(membership.workspace)}/datasets/").status_code
            == 200
        )

    def test_dataset_detail_is_tenant_scoped(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        foreign = EvaluationDatasetFactory()
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/datasets/{foreign.id}/"
        )
        assert response.status_code == 404

    def test_manager_patches_a_dataset(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset = EvaluationDatasetFactory(workspace=membership.workspace, name="Old")
        response = _client(membership.user).patch(
            f"{_base(membership.workspace)}/datasets/{dataset.id}/",
            {"name": "New", "status": "active"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["name"] == "New"
        assert response.data["status"] == "active"

    def test_support_agent_cannot_patch_a_dataset(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        dataset = EvaluationDatasetFactory(workspace=membership.workspace)
        response = _client(membership.user).patch(
            f"{_base(membership.workspace)}/datasets/{dataset.id}/",
            {"name": "New"},
            format="json",
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestCaseApi:
    def test_case_create_validates_schema(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset = EvaluationDatasetFactory(workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/datasets/{dataset.id}/cases/",
            {
                "key": "order-status",
                "name": "Order status",
                "input_message": "Where is my order?",
                "expectations": {"unexpected_field": "not allowed"},
            },
            format="json",
        )
        assert response.status_code == 400

    def test_case_create_and_list(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset = EvaluationDatasetFactory(workspace=membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/datasets/{dataset.id}/cases/",
            {
                "key": "order-status",
                "name": "Order status",
                "input_message": "Where is my order?",
            },
            format="json",
        )
        assert response.status_code == 201
        listing = _client(membership.user).get(
            f"{_base(membership.workspace)}/datasets/{dataset.id}/cases/"
        )
        assert listing.status_code == 200
        assert listing.data["count"] == 1

    def test_case_patch_and_detail(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset = EvaluationDatasetFactory(workspace=membership.workspace)
        case = EvaluationCaseFactory(dataset=dataset)
        detail = _client(membership.user).get(
            f"{_base(membership.workspace)}/datasets/{dataset.id}/cases/{case.id}/"
        )
        assert detail.status_code == 200
        response = _client(membership.user).patch(
            f"{_base(membership.workspace)}/datasets/{dataset.id}/cases/{case.id}/",
            {"status": "disabled"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["status"] == "disabled"

    def test_case_in_foreign_dataset_is_404_even_for_own_workspace_member(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        foreign_dataset = EvaluationDatasetFactory()
        foreign_case = EvaluationCaseFactory(dataset=foreign_dataset)
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/datasets/{foreign_dataset.id}/cases/{foreign_case.id}/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestRunApi:
    def _dataset_and_version(self, workspace):
        dataset = EvaluationDatasetFactory(workspace=workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=workspace)
        return dataset, version

    def test_trigger_run_requires_run_role(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        dataset, version = self._dataset_and_version(membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/runs/",
            {"dataset_id": str(dataset.id), "agent_version_id": str(version.id)},
            format="json",
        )
        assert response.status_code == 403

    def test_trigger_run_with_foreign_agent_version_is_404(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset = EvaluationDatasetFactory(workspace=membership.workspace)
        EvaluationCaseFactory(dataset=dataset)
        foreign_version = PublishedAgentVersionFactory()
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/runs/",
            {"dataset_id": str(dataset.id), "agent_version_id": str(foreign_version.id)},
            format="json",
        )
        assert response.status_code == 404

    def test_trigger_run_then_read_results_and_cancel(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset, version = self._dataset_and_version(membership.workspace)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/runs/",
            {"dataset_id": str(dataset.id), "agent_version_id": str(version.id)},
            format="json",
        )
        assert response.status_code == 201
        run_id = response.data["id"]

        results = _client(membership.user).get(
            f"{_base(membership.workspace)}/runs/{run_id}/results/"
        )
        assert results.status_code == 200
        assert results.data["count"] == 1

        cancel = _client(membership.user).post(
            f"{_base(membership.workspace)}/runs/{run_id}/cancel/"
        )
        assert cancel.status_code == 200
        assert cancel.data["status"] == "cancelled"

        # Cancelling an already-cancelled run is a conflict, not a silent 200.
        cancel_again = _client(membership.user).post(
            f"{_base(membership.workspace)}/runs/{run_id}/cancel/"
        )
        assert cancel_again.status_code == 409

    def test_run_detail_is_tenant_scoped(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        dataset, version = self._dataset_and_version(WorkspaceFactory())
        foreign_run = services.start_evaluation_run(
            workspace=dataset.workspace,
            actor=membership.user,
            dataset=dataset,
            agent_version=version,
        )
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/runs/{foreign_run.id}/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestReplayAndCompareApi:
    def test_replay_requires_run_role_and_returns_201(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset = EvaluationDatasetFactory(workspace=membership.workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        run = services.start_evaluation_run(
            workspace=membership.workspace,
            actor=membership.user,
            dataset=dataset,
            agent_version=version,
        )
        result = services.execute_evaluation_case(run.results.get().id)

        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/runs/{run.id}/results/{result.id}/replay/"
        )
        assert response.status_code == 201
        assert response.data["replay_of_id"] == str(result.id)

    def test_compare_rejects_incompatible_runs(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset_a = EvaluationDatasetFactory(workspace=membership.workspace)
        EvaluationCaseFactory(dataset=dataset_a, key="a")
        dataset_b = EvaluationDatasetFactory(workspace=membership.workspace)
        EvaluationCaseFactory(dataset=dataset_b, key="b")
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        run_a = services.start_evaluation_run(
            workspace=membership.workspace,
            actor=membership.user,
            dataset=dataset_a,
            agent_version=version,
        )
        run_b = services.start_evaluation_run(
            workspace=membership.workspace,
            actor=membership.user,
            dataset=dataset_b,
            agent_version=version,
        )
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/compare/",
            {"baseline_run_id": str(run_a.id), "candidate_run_id": str(run_b.id)},
            format="json",
        )
        assert response.status_code == 400
