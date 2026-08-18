"""Ticket API tests: RBAC matrix, assignment, status lifecycle, and
cross-tenant isolation."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from customers.tests.factories import CustomerFactory
from tickets.models import TicketStatus
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import TicketFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture
def workspace():
    return WorkspaceFactory()


@pytest.mark.django_db
class TestTicketListCreateView:
    def test_requires_authentication(self, workspace):
        response = _client().get(f"/api/v1/workspaces/{workspace.id}/tickets/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_agent_can_create_ticket(self, workspace):
        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        customer = CustomerFactory(workspace=workspace)

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/",
            {"customer_id": str(customer.id), "subject": "Broken widget"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_viewer_cannot_create_ticket(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        customer = CustomerFactory(workspace=workspace)

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/",
            {"customer_id": str(customer.id), "subject": "Broken widget"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_foreign_customer_id_is_rejected_safely(self, workspace):
        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        foreign_customer = CustomerFactory(workspace=WorkspaceFactory())

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/",
            {"customer_id": str(foreign_customer.id), "subject": "x"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_filters_by_unassigned(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        TicketFactory(workspace=workspace)
        assigned_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        TicketFactory(workspace=workspace, assigned_to=assigned_agent)

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/tickets/", {"unassigned": "true"}
        )

        assert response.data["count"] == 1

    def test_filters_by_priority(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        TicketFactory(workspace=workspace, priority="urgent")
        TicketFactory(workspace=workspace, priority="low")

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/tickets/", {"priority": "urgent"}
        )

        assert response.data["count"] == 1


@pytest.mark.django_db
class TestTicketDetailView:
    def test_member_can_retrieve_ticket(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        ticket = TicketFactory(workspace=workspace)

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(ticket.id)

    def test_agent_can_update_ticket_assigned_to_them(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, assigned_to=agent)

        response = _client(agent.user).patch(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/",
            {"subject": "Updated"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK

    def test_agent_cannot_update_unassigned_ticket(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace)

        response = _client(agent.user).patch(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/",
            {"subject": "Updated"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_foreign_ticket_returns_404(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.OWNER)
        foreign_ticket = TicketFactory()

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/tickets/{foreign_ticket.id}/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestTicketAssignmentViews:
    def test_manager_assigns_ticket(self, workspace):
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace)

        response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/assign/",
            {"membership_id": str(agent.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["assigned_to"]["id"] == str(agent.id)

    def test_agent_self_assigns(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace)

        response = _client(agent.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/assign/", {}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["assigned_to"]["id"] == str(agent.id)

    def test_agent_cannot_unassign(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, assigned_to=agent)

        response = _client(agent.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/unassign/"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_manager_can_unassign(self, workspace):
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, assigned_to=agent)

        response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/unassign/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["assigned_to"] is None


@pytest.mark.django_db
class TestTicketStatusViews:
    def test_resolve_then_reopen(self, workspace):
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        ticket = TicketFactory(workspace=workspace, status=TicketStatus.OPEN)

        resolve_response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/resolve/"
        )
        assert resolve_response.status_code == status.HTTP_200_OK
        assert resolve_response.data["status"] == "resolved"
        assert resolve_response.data["resolved_at"] is not None

        reopen_response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/reopen/"
        )
        assert reopen_response.status_code == status.HTTP_200_OK
        assert reopen_response.data["status"] == "open"
        assert reopen_response.data["resolved_at"] is None

    def test_generic_status_endpoint(self, workspace):
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        ticket = TicketFactory(workspace=workspace, status=TicketStatus.OPEN)

        response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/status/",
            {"status": "in_progress"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "in_progress"


@pytest.mark.django_db
class TestTicketRbacMatrix:
    @pytest.mark.parametrize(
        "role,can_create",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, True),
            (WorkspaceRole.SUPPORT_AGENT, True),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_create_permission_by_role(self, workspace, role, can_create):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=role)
        customer = CustomerFactory(workspace=workspace)

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/",
            {"customer_id": str(customer.id), "subject": "x"},
            format="json",
        )

        expected = status.HTTP_201_CREATED if can_create else status.HTTP_403_FORBIDDEN
        assert response.status_code == expected

    @pytest.mark.parametrize(
        "role,can_reassign",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, True),
            (WorkspaceRole.SUPPORT_AGENT, False),
        ],
    )
    def test_reassign_permission_by_role(self, workspace, role, can_reassign):
        actor = WorkspaceMembershipFactory(workspace=workspace, role=role)
        already_assigned_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        target = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, assigned_to=already_assigned_agent)

        response = _client(actor.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/{ticket.id}/assign/",
            {"membership_id": str(target.id)},
            format="json",
        )

        expected = status.HTTP_200_OK if can_reassign else status.HTTP_403_FORBIDDEN
        assert response.status_code == expected


@pytest.mark.django_db
class TestTicketCrossTenantIsolation:
    def test_anonymous_gets_401(self, workspace):
        response = _client().get(f"/api/v1/workspaces/{workspace.id}/tickets/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_of_workspace_b_cannot_update_workspace_a_ticket(self):
        workspace_a = WorkspaceFactory()
        workspace_b = WorkspaceFactory()
        membership_b = WorkspaceMembershipFactory(workspace=workspace_b, role=WorkspaceRole.OWNER)
        ticket_a = TicketFactory(workspace=workspace_a)

        response = _client(membership_b.user).patch(
            f"/api/v1/workspaces/{workspace_a.id}/tickets/{ticket_a.id}/",
            {"subject": "Hijacked"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_conversation_id_in_create_payload_is_rejected_safely(self, workspace):
        from conversations.tests.factories import ConversationFactory

        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        customer = CustomerFactory(workspace=workspace)
        foreign_conversation = ConversationFactory()

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/tickets/",
            {
                "customer_id": str(customer.id),
                "conversation_id": str(foreign_conversation.id),
                "subject": "x",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
