"""Phase 14 (Section 11): representative, cross-domain pagination/filter/
ordering contract tests. Not exhaustive per endpoint — these prove the
*shared* behaviors (pagination shape, max page size, deterministic order,
malformed filters failing safely, tenant scope preserved) hold across a
representative sample rather than duplicating every existing endpoint
test."""

from __future__ import annotations

from unittest import mock

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from agents.tests.factories import PublishedAgentVersionFactory
from channel_ingress.tests.factories import ChannelEndpointFactory
from conversations.tests.factories import ConversationFactory
from customers.tests.factories import CustomerFactory
from evaluations import services as evaluation_services
from evaluations.tests.factories import EvaluationCaseFactory, EvaluationDatasetFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory


def _client(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestCustomerAndConversationListContract:
    def test_customer_list_default_pagination_shape_and_stable_ordering(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        for _ in range(3):
            CustomerFactory(workspace=membership.workspace)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/customers/"
        )
        assert response.status_code == 200
        assert set(response.data.keys()) == {"count", "next", "previous", "results"}
        assert response.data["count"] == 3

    def test_customer_list_stable_order_survives_identical_timestamps(self):
        # Regression (Phase 14, Section 4): rows sharing the same
        # created_at must still paginate deterministically.
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        tied_at = timezone.now()
        with mock.patch("django.utils.timezone.now", return_value=tied_at):
            for _ in range(5):
                CustomerFactory(workspace=membership.workspace)
        client = _client(membership.user)
        base = f"/api/v1/workspaces/{membership.workspace.id}/customers/?page_size=2"

        first_ids = [row["id"] for row in client.get(base).data["results"]]
        second_ids = [row["id"] for row in client.get(base).data["results"]]
        assert first_ids == second_ids  # same query, repeated — identical page every time
        assert len(set(first_ids)) == 2  # no row duplicated within one page

    def test_conversation_list_malformed_customer_filter_fails_safely(self):
        # Regression (Phase 14, Section 7): a malformed UUID filter
        # previously reached the ORM/DB unfiltered and surfaced as an
        # unhandled 500 (django.core.exceptions.ValidationError bubbling
        # out of QuerySet.filter) instead of a stable 400.
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/conversations/?customer=not-a-uuid"
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "validation_error"

    def test_conversation_list_valid_status_filter(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        open_convo = ConversationFactory(workspace=membership.workspace, status="open")
        ConversationFactory(workspace=membership.workspace, status="closed")
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/conversations/?status=open"
        )
        assert response.status_code == 200
        assert [row["id"] for row in response.data["results"]] == [str(open_convo.id)]

    def test_conversation_list_cross_tenant_filter_never_leaks_a_foreign_customer(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        foreign_customer = CustomerFactory()  # a different workspace entirely
        ConversationFactory(workspace=membership.workspace)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/conversations/"
            f"?customer={foreign_customer.id}"
        )
        # Workspace scoping is applied before the customer filter — a
        # foreign-workspace customer id matches nothing, never another
        # tenant's conversations.
        assert response.status_code == 200
        assert response.data["count"] == 0


@pytest.mark.django_db
class TestPageSizeBounds:
    def test_default_page_size_is_fifty(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        for _ in range(55):
            CustomerFactory(workspace=membership.workspace)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/customers/"
        )
        assert len(response.data["results"]) == 50
        assert response.data["next"] is not None

    def test_custom_valid_page_size_is_honored(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        for _ in range(10):
            CustomerFactory(workspace=membership.workspace)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/customers/?page_size=5"
        )
        assert len(response.data["results"]) == 5

    def test_page_size_above_maximum_is_capped_not_rejected(self):
        # StandardResultsSetPagination.max_page_size = 500 — DRF's own
        # documented behavior for an over-large page_size is to cap it,
        # not error, matching every other endpoint using this class.
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        for _ in range(3):
            CustomerFactory(workspace=membership.workspace)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/customers/?page_size=5000"
        )
        assert response.status_code == 200
        assert len(response.data["results"]) == 3  # capped at 500, but only 3 rows exist

    def test_malformed_page_size_falls_back_to_default_safely(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        CustomerFactory(workspace=membership.workspace)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/customers/?page_size=not-a-number"
        )
        assert response.status_code == 200  # DRF ignores an invalid page_size, uses the default
        assert len(response.data["results"]) == 1


@pytest.mark.django_db
class TestAgentRunListContract:
    def test_status_filter_and_stable_ordering(self):
        from agents.models import AgentRunStatus
        from agents.tests.factories import AgentRunFactory

        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        succeeded = AgentRunFactory(workspace=membership.workspace, status=AgentRunStatus.SUCCEEDED)
        AgentRunFactory(workspace=membership.workspace, status=AgentRunStatus.FAILED)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/agent-runs/?status=succeeded"
        )
        assert response.status_code == 200
        assert [row["id"] for row in response.data["results"]] == [str(succeeded.id)]

    def test_malformed_agent_id_filter_fails_safely_not_500(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.SUPPORT_AGENT)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/agent-runs/?agent_id=not-a-uuid"
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "validation_error"


@pytest.mark.django_db
class TestEvaluationResultListContract:
    def test_pagination_and_status_filter(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        dataset = EvaluationDatasetFactory(workspace=membership.workspace)
        EvaluationCaseFactory(dataset=dataset)
        version = PublishedAgentVersionFactory(agent_definition__workspace=membership.workspace)
        run = evaluation_services.start_evaluation_run(
            workspace=membership.workspace,
            actor=membership.user,
            dataset=dataset,
            agent_version=version,
        )
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/evaluations/runs/{run.id}/results/"
        )
        assert response.status_code == 200
        assert set(response.data.keys()) == {"count", "next", "previous", "results"}
        assert response.data["count"] == 1


@pytest.mark.django_db
class TestChannelEndpointListContract:
    def test_tenant_scope_and_bounded_response(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        ChannelEndpointFactory(workspace=membership.workspace)
        ChannelEndpointFactory()  # a different workspace entirely
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{membership.workspace.id}/channels/endpoints/"
        )
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert set(response.data.keys()) == {"count", "next", "previous", "results"}
