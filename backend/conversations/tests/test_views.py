"""Conversation and message API tests: RBAC, filtering, sender-impersonation
protection, and cross-tenant isolation."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from conversations.models import ConversationStatus
from customers.tests.factories import CustomerFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import ConversationFactory, MessageFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture
def workspace():
    return WorkspaceFactory()


@pytest.mark.django_db
class TestConversationListCreateView:
    def test_requires_authentication(self, workspace):
        response = _client().get(f"/api/v1/workspaces/{workspace.id}/conversations/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_can_create_conversation(self, workspace):
        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        customer = CustomerFactory(workspace=workspace)

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/",
            {"customer_id": str(customer.id), "channel": "web"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_viewer_cannot_create_conversation(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        customer = CustomerFactory(workspace=workspace)

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/",
            {"customer_id": str(customer.id), "channel": "web"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_foreign_customer_id_in_create_payload_is_rejected_safely(self, workspace):
        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        foreign_customer = CustomerFactory(workspace=WorkspaceFactory())

        response = _client(membership.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/",
            {"customer_id": str(foreign_customer.id), "channel": "web"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_filters_by_status(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        ConversationFactory(workspace=workspace, status=ConversationStatus.OPEN)
        ConversationFactory(workspace=workspace, status=ConversationStatus.CLOSED)

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/conversations/", {"status": "open"}
        )

        assert response.data["count"] == 1

    def test_filters_by_unassigned(self, workspace):
        membership = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        ConversationFactory(workspace=workspace)
        assigned_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        ConversationFactory(workspace=workspace, assigned_to=assigned_agent)

        response = _client(membership.user).get(
            f"/api/v1/workspaces/{workspace.id}/conversations/", {"unassigned": "true"}
        )

        assert response.data["count"] == 1


@pytest.mark.django_db
class TestConversationAssignView:
    def test_manager_can_assign_to_any_member(self, workspace):
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/assign/",
            {"membership_id": str(agent.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["assigned_to"]["id"] == str(agent.id)

    def test_agent_self_assigns_when_no_membership_supplied(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        response = _client(agent.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/assign/",
            {},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["assigned_to"]["id"] == str(agent.id)

    def test_agent_cannot_assign_to_another_agent(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        peer = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        response = _client(agent.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/assign/",
            {"membership_id": str(peer.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_cannot_assign(self, workspace):
        viewer = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        conversation = ConversationFactory(workspace=workspace)

        response = _client(viewer.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/assign/",
            {},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_foreign_membership_id_is_rejected_safely(self, workspace):
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        foreign_membership = WorkspaceMembershipFactory(workspace=WorkspaceFactory())
        conversation = ConversationFactory(workspace=workspace)

        response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/assign/",
            {"membership_id": str(foreign_membership.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestConversationCloseReopenView:
    def test_close_then_reopen(self, workspace):
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        conversation = ConversationFactory(workspace=workspace, status=ConversationStatus.OPEN)

        close_response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/close/"
        )
        assert close_response.status_code == status.HTTP_200_OK
        assert close_response.data["status"] == "closed"

        reopen_response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/reopen/"
        )
        assert reopen_response.status_code == status.HTTP_200_OK
        assert reopen_response.data["status"] == "open"

    def test_foreign_conversation_close_returns_404(self, workspace):
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        foreign_conversation = ConversationFactory()

        response = _client(manager.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{foreign_conversation.id}/close/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestMessageListCreateView:
    def test_agent_can_send_outbound_message(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        response = _client(agent.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages/",
            {"direction": "outbound", "body": "How can I help?"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["sender"]["id"] == str(agent.id)
        assert response.data["sender_type"] == "human_agent"

    def test_agent_can_send_internal_message(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        response = _client(agent.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages/",
            {"direction": "internal", "body": "internal note"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["direction"] == "internal"

    def test_viewer_cannot_send_message(self, workspace):
        viewer = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        conversation = ConversationFactory(workspace=workspace)

        response = _client(viewer.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages/",
            {"direction": "outbound", "body": "Hi"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_client_cannot_impersonate_customer_sender(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        response = _client(agent.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages/",
            {"direction": "inbound", "sender_type": "customer", "body": "fake customer message"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_member_can_list_messages(self, workspace):
        viewer = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        conversation = ConversationFactory(workspace=workspace)
        MessageFactory(conversation=conversation)

        response = _client(viewer.user).get(
            f"/api/v1/workspaces/{workspace.id}/conversations/{conversation.id}/messages/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

    def test_foreign_conversation_message_post_returns_404(self, workspace):
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        foreign_conversation = ConversationFactory()

        response = _client(agent.user).post(
            f"/api/v1/workspaces/{workspace.id}/conversations/{foreign_conversation.id}/messages/",
            {"direction": "outbound", "body": "Hi"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestConversationCrossTenantIsolation:
    def test_anonymous_gets_401(self, workspace):
        response = _client().get(f"/api/v1/workspaces/{workspace.id}/conversations/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_of_workspace_b_cannot_retrieve_workspace_a_conversation(self):
        workspace_a = WorkspaceFactory()
        workspace_b = WorkspaceFactory()
        membership_b = WorkspaceMembershipFactory(workspace=workspace_b, role=WorkspaceRole.OWNER)
        conversation_a = ConversationFactory(workspace=workspace_a)

        response = _client(membership_b.user).get(
            f"/api/v1/workspaces/{workspace_a.id}/conversations/{conversation_a.id}/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
