"""Consolidated cross-tenant regression matrix for the ticket domain."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from conversations.tests.factories import ConversationFactory
from customers.tests.factories import CustomerFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import TicketFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture
def two_workspaces():
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    membership_a = WorkspaceMembershipFactory(workspace=workspace_a, role=WorkspaceRole.OWNER)
    membership_b = WorkspaceMembershipFactory(workspace=workspace_b, role=WorkspaceRole.OWNER)
    customer_a = CustomerFactory(workspace=workspace_a)
    conversation_a = ConversationFactory(workspace=workspace_a, customer=customer_a)
    ticket_a = TicketFactory(workspace=workspace_a, customer=customer_a)
    return {
        "workspace_a": workspace_a,
        "workspace_b": workspace_b,
        "membership_a": membership_a,
        "membership_b": membership_b,
        "customer_a": customer_a,
        "conversation_a": conversation_a,
        "ticket_a": ticket_a,
    }


@pytest.mark.django_db
class TestTicketCrossTenantMatrix:
    @pytest.mark.parametrize(
        "build_request",
        [
            lambda d: ("get", f"/api/v1/workspaces/{d['workspace_a'].id}/tickets/", None),
            lambda d: (
                "get",
                f"/api/v1/workspaces/{d['workspace_a'].id}/tickets/{d['ticket_a'].id}/",
                None,
            ),
            lambda d: (
                "patch",
                f"/api/v1/workspaces/{d['workspace_a'].id}/tickets/{d['ticket_a'].id}/",
                {"subject": "Hijacked"},
            ),
            lambda d: (
                "post",
                f"/api/v1/workspaces/{d['workspace_a'].id}/tickets/{d['ticket_a'].id}/assign/",
                {"membership_id": str(d["membership_a"].id)},
            ),
            lambda d: (
                "post",
                f"/api/v1/workspaces/{d['workspace_a'].id}/tickets/{d['ticket_a'].id}/resolve/",
                None,
            ),
        ],
    )
    def test_member_of_b_gets_404_on_workspace_a_resources(self, two_workspaces, build_request):
        method, path, payload = build_request(two_workspaces)
        response = getattr(_client(two_workspaces["membership_b"].user), method)(
            path, payload, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_workspace_b_cannot_create_ticket_for_workspace_a_customer(self, two_workspaces):
        response = _client(two_workspaces["membership_b"].user).post(
            f"/api/v1/workspaces/{two_workspaces['workspace_b'].id}/tickets/",
            {"customer_id": str(two_workspaces["customer_a"].id), "subject": "x"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_workspace_b_cannot_attach_workspace_a_conversation_to_new_ticket(self, two_workspaces):
        own_customer = CustomerFactory(workspace=two_workspaces["workspace_b"])
        response = _client(two_workspaces["membership_b"].user).post(
            f"/api/v1/workspaces/{two_workspaces['workspace_b'].id}/tickets/",
            {
                "customer_id": str(own_customer.id),
                "conversation_id": str(two_workspaces["conversation_a"].id),
                "subject": "x",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_anonymous_gets_401(self, two_workspaces):
        response = _client().get(f"/api/v1/workspaces/{two_workspaces['workspace_a'].id}/tickets/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
