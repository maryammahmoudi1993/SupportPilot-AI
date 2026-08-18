"""Conversation and message service tests: assignment rules, status
transitions, and activity-timestamp invariants."""

import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError

from audit.models import AuditEvent
from conversations import services
from conversations.models import ConversationStatus
from customers.tests.factories import CustomerFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import ConversationFactory


@pytest.mark.django_db
class TestCreateConversation:
    def test_creates_conversation_for_customer_in_workspace(self):
        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)

        conversation = services.create_conversation(
            workspace=workspace, customer=customer, channel="web"
        )

        assert conversation.workspace_id == workspace.id
        assert conversation.status == ConversationStatus.OPEN

    def test_foreign_customer_is_rejected(self):
        workspace = WorkspaceFactory()
        foreign_customer = CustomerFactory(workspace=WorkspaceFactory())

        with pytest.raises(ValidationError):
            services.create_conversation(
                workspace=workspace, customer=foreign_customer, channel="web"
            )


@pytest.mark.django_db
class TestAssignConversation:
    def test_manager_can_assign_to_any_member(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        updated = services.assign_conversation(
            workspace=workspace,
            actor=manager.user,
            actor_membership=manager,
            conversation=conversation,
            target_membership=agent,
        )

        assert updated.assigned_to_id == agent.id
        assert AuditEvent.objects.filter(action="conversation.assigned").exists()

    def test_manager_reassigning_records_reassigned_event(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        first_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        second_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        conversation = ConversationFactory(workspace=workspace, assigned_to=first_agent)

        services.assign_conversation(
            workspace=workspace,
            actor=manager.user,
            actor_membership=manager,
            conversation=conversation,
            target_membership=second_agent,
        )

        assert AuditEvent.objects.filter(action="conversation.reassigned").exists()

    def test_agent_can_self_assign_unassigned_conversation(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        updated = services.self_assign_conversation(
            workspace=workspace, actor=agent.user, actor_membership=agent, conversation=conversation
        )

        assert updated.assigned_to_id == agent.id

    def test_agent_cannot_assign_to_a_peer(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        peer = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        with pytest.raises(PermissionDenied):
            services.assign_conversation(
                workspace=workspace,
                actor=agent.user,
                actor_membership=agent,
                conversation=conversation,
                target_membership=peer,
            )

    def test_agent_cannot_reassign_a_conversation_already_assigned_to_someone_else(self):
        workspace = WorkspaceFactory()
        first_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        second_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        conversation = ConversationFactory(workspace=workspace, assigned_to=first_agent)

        with pytest.raises(PermissionDenied):
            services.assign_conversation(
                workspace=workspace,
                actor=second_agent.user,
                actor_membership=second_agent,
                conversation=conversation,
                target_membership=second_agent,
            )

    def test_target_membership_from_another_workspace_is_rejected(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        foreign_membership = WorkspaceMembershipFactory(workspace=WorkspaceFactory())
        conversation = ConversationFactory(workspace=workspace)

        with pytest.raises(ValidationError):
            services.assign_conversation(
                workspace=workspace,
                actor=manager.user,
                actor_membership=manager,
                conversation=conversation,
                target_membership=foreign_membership,
            )


@pytest.mark.django_db
class TestChangeConversationStatus:
    def test_open_to_pending_is_allowed(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        conversation = ConversationFactory(workspace=workspace, status=ConversationStatus.OPEN)

        updated = services.change_conversation_status(
            workspace=workspace,
            actor=manager.user,
            actor_membership=manager,
            conversation=conversation,
            new_status=ConversationStatus.PENDING,
        )

        assert updated.status == ConversationStatus.PENDING

    def test_closing_sets_closed_at(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        conversation = ConversationFactory(workspace=workspace, status=ConversationStatus.OPEN)

        updated = services.close_conversation(
            workspace=workspace,
            actor=manager.user,
            actor_membership=manager,
            conversation=conversation,
        )

        assert updated.status == ConversationStatus.CLOSED
        assert updated.closed_at is not None
        assert AuditEvent.objects.filter(action="conversation.closed").exists()

    def test_reopening_clears_closed_at(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        conversation = ConversationFactory(workspace=workspace, status=ConversationStatus.OPEN)
        conversation = services.close_conversation(
            workspace=workspace,
            actor=manager.user,
            actor_membership=manager,
            conversation=conversation,
        )

        updated = services.reopen_conversation(
            workspace=workspace,
            actor=manager.user,
            actor_membership=manager,
            conversation=conversation,
        )

        assert updated.status == ConversationStatus.OPEN
        assert updated.closed_at is None
        assert AuditEvent.objects.filter(action="conversation.reopened").exists()

    def test_invalid_transition_is_rejected(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        conversation = ConversationFactory(workspace=workspace, status=ConversationStatus.CLOSED)

        with pytest.raises(ValidationError):
            services.change_conversation_status(
                workspace=workspace,
                actor=manager.user,
                actor_membership=manager,
                conversation=conversation,
                new_status=ConversationStatus.PENDING,
            )

    def test_agent_cannot_close_conversation_not_assigned_to_them(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace, status=ConversationStatus.OPEN)

        with pytest.raises(PermissionDenied):
            services.close_conversation(
                workspace=workspace,
                actor=agent.user,
                actor_membership=agent,
                conversation=conversation,
            )

    def test_agent_can_close_conversation_assigned_to_them(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(
            workspace=workspace, status=ConversationStatus.OPEN, assigned_to=agent
        )

        updated = services.close_conversation(
            workspace=workspace, actor=agent.user, actor_membership=agent, conversation=conversation
        )

        assert updated.status == ConversationStatus.CLOSED


@pytest.mark.django_db
class TestMessageCreationUpdatesConversationActivity:
    def test_creating_message_updates_last_message_at(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace, last_message_at=None)

        services.create_outbound_message(
            workspace=workspace, actor_membership=agent, conversation=conversation, body="Hi there"
        )

        conversation.refresh_from_db()
        assert conversation.last_message_at is not None

    def test_outbound_message_sender_is_the_authenticated_agent(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        message = services.create_outbound_message(
            workspace=workspace, actor_membership=agent, conversation=conversation, body="Hi"
        )

        assert message.sender_membership_id == agent.id
        assert message.sender_type == "human_agent"
        assert message.direction == "outbound"

    def test_internal_message_is_marked_internal(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace)

        message = services.create_internal_message(
            workspace=workspace,
            actor_membership=agent,
            conversation=conversation,
            body="internal note",
        )

        assert message.direction == "internal"

    def test_inbound_message_reopens_closed_conversation(self):
        workspace = WorkspaceFactory()
        conversation = ConversationFactory(workspace=workspace, status=ConversationStatus.CLOSED)
        from django.utils import timezone

        conversation.closed_at = timezone.now()
        conversation.save(update_fields=["closed_at"])

        services.create_inbound_message(
            workspace=workspace, conversation=conversation, body="Still there?"
        )

        conversation.refresh_from_db()
        assert conversation.status == ConversationStatus.OPEN
        assert conversation.closed_at is None

    def test_outbound_message_on_closed_conversation_does_not_reopen_it(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        conversation = ConversationFactory(workspace=workspace, status=ConversationStatus.CLOSED)

        services.create_outbound_message(
            workspace=workspace, actor_membership=agent, conversation=conversation, body="Reply"
        )

        conversation.refresh_from_db()
        assert conversation.status == ConversationStatus.CLOSED

    def test_sender_membership_from_another_workspace_is_rejected(self):
        workspace = WorkspaceFactory()
        conversation = ConversationFactory(workspace=workspace)
        foreign_membership = WorkspaceMembershipFactory(workspace=WorkspaceFactory())

        with pytest.raises(ValidationError):
            services.create_outbound_message(
                workspace=workspace,
                actor_membership=foreign_membership,
                conversation=conversation,
                body="Hi",
            )

    def test_message_on_foreign_conversation_is_rejected(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        foreign_conversation = ConversationFactory()

        with pytest.raises(ValidationError):
            services.create_outbound_message(
                workspace=workspace,
                actor_membership=agent,
                conversation=foreign_conversation,
                body="Hi",
            )
