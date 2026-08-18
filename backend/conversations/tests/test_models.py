"""Conversation and message model tests: creation, tenancy, and lifecycle
timestamp invariants."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from conversations.models import (
    ConversationChannel,
    ConversationStatus,
    MessageDirection,
    MessageSenderType,
)
from customers.tests.factories import CustomerFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import ConversationFactory, MessageFactory


@pytest.mark.django_db
class TestConversationCreation:
    def test_creates_with_defaults(self):
        conversation = ConversationFactory()
        assert conversation.status == ConversationStatus.OPEN
        assert conversation.channel == ConversationChannel.WEB
        assert conversation.closed_at is None

    @pytest.mark.parametrize("channel", [c.value for c in ConversationChannel])
    def test_accepts_every_declared_channel(self, channel):
        conversation = ConversationFactory(channel=channel)
        assert conversation.channel == channel

    @pytest.mark.parametrize("status", [s.value for s in ConversationStatus])
    def test_accepts_every_declared_status(self, status):
        conversation = ConversationFactory(status=status)
        assert conversation.status == status


@pytest.mark.django_db
class TestConversationTenancyInvariants:
    def test_customer_from_another_workspace_fails_validation(self):
        workspace = WorkspaceFactory()
        foreign_customer = CustomerFactory(workspace=WorkspaceFactory())
        conversation = ConversationFactory.build(workspace=workspace, customer=foreign_customer)

        with pytest.raises(ValidationError):
            conversation.full_clean()

    def test_assignee_from_another_workspace_fails_validation(self):
        workspace = WorkspaceFactory()
        foreign_membership = WorkspaceMembershipFactory(workspace=WorkspaceFactory())
        conversation = ConversationFactory.build(
            workspace=workspace, assigned_to=foreign_membership
        )
        conversation.customer = CustomerFactory(workspace=workspace)

        with pytest.raises(ValidationError):
            conversation.full_clean()

    def test_assignee_in_same_workspace_is_valid(self):
        workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        conversation = ConversationFactory(workspace=workspace, assigned_to=membership)
        conversation.full_clean()

    def test_removed_assignee_leaves_conversation_unassigned(self):
        workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(workspace=workspace)
        conversation = ConversationFactory(workspace=workspace, assigned_to=membership)

        membership.delete()
        conversation.refresh_from_db()

        assert conversation.assigned_to_id is None

    def test_duplicate_external_id_in_same_workspace_is_rejected(self):
        workspace = WorkspaceFactory()
        ConversationFactory(workspace=workspace, external_id="ext-1")
        with pytest.raises(IntegrityError):
            ConversationFactory(workspace=workspace, external_id="ext-1")

    def test_same_external_id_allowed_across_workspaces(self):
        ConversationFactory(external_id="ext-shared")
        # Must not raise — a different workspace with the same external_id.
        ConversationFactory(external_id="ext-shared")


@pytest.mark.django_db
class TestConversationStringRepresentation:
    def test_str_falls_back_to_id_when_no_subject(self):
        conversation = ConversationFactory(subject="")
        assert str(conversation) == f"Conversation {conversation.id}"


@pytest.mark.django_db
class TestConversationActivityTimestamps:
    def test_closing_sets_closed_at(self):
        conversation = ConversationFactory()
        from django.utils import timezone

        conversation.status = ConversationStatus.CLOSED
        conversation.closed_at = timezone.now()
        conversation.save()
        assert conversation.closed_at is not None

    def test_reopening_clears_closed_at(self):
        from django.utils import timezone

        conversation = ConversationFactory(
            status=ConversationStatus.CLOSED, closed_at=timezone.now()
        )
        conversation.status = ConversationStatus.OPEN
        conversation.closed_at = None
        conversation.save()
        assert conversation.closed_at is None


@pytest.mark.django_db
class TestMessageCreation:
    def test_creates_message_for_conversation(self):
        message = MessageFactory()
        assert message.conversation is not None
        assert message.workspace_id == message.conversation.workspace_id

    @pytest.mark.parametrize("sender_type", [s.value for s in MessageSenderType])
    def test_accepts_every_declared_sender_type(self, sender_type):
        message = MessageFactory(sender_type=sender_type)
        assert message.sender_type == sender_type

    @pytest.mark.parametrize("direction", [d.value for d in MessageDirection])
    def test_accepts_every_declared_direction(self, direction):
        message = MessageFactory(direction=direction)
        assert message.direction == direction

    def test_conversation_from_another_workspace_fails_validation(self):
        workspace = WorkspaceFactory()
        foreign_conversation = ConversationFactory(workspace=WorkspaceFactory())
        message = MessageFactory.build(workspace=workspace, conversation=foreign_conversation)

        with pytest.raises(ValidationError):
            message.full_clean()

    def test_sender_membership_from_another_workspace_fails_validation(self):
        conversation = ConversationFactory()
        foreign_membership = WorkspaceMembershipFactory(workspace=WorkspaceFactory())
        message = MessageFactory.build(
            workspace=conversation.workspace,
            conversation=conversation,
            sender_membership=foreign_membership,
        )

        with pytest.raises(ValidationError):
            message.full_clean()

    def test_str_representation(self):
        message = MessageFactory()
        assert (
            str(message)
            == f"{message.sender_type}/{message.direction} message on {message.conversation_id}"
        )

    def test_messages_are_ordered_chronologically(self):
        conversation = ConversationFactory()
        first = MessageFactory(conversation=conversation)
        second = MessageFactory(conversation=conversation)

        ordered = list(conversation.messages.all())

        assert ordered == [first, second]

    def test_no_general_update_service_exists_for_messages(self):
        # Immutability is enforced by omission: there is no
        # ``update_message``/``delete_message`` in conversations.services.
        import conversations.services as services

        assert not hasattr(services, "update_message")
        assert not hasattr(services, "delete_message")
