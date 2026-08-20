"""Conversation and message selector tests: tenant isolation, filtering, and
ordering."""

import pytest
from django.http import Http404

from conversations import selectors
from conversations.models import ConversationStatus
from customers.tests.factories import CustomerFactory
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import ConversationFactory, MessageFactory


@pytest.mark.django_db
class TestConversationListForWorkspace:
    def test_only_returns_conversations_in_the_given_workspace(self):
        workspace_a = WorkspaceFactory()
        in_a = ConversationFactory(workspace=workspace_a)
        ConversationFactory()

        results = list(selectors.conversation_list_for_workspace(workspace=workspace_a))

        assert results == [in_a]

    def test_filters_by_status(self):
        workspace = WorkspaceFactory()
        open_conv = ConversationFactory(workspace=workspace, status=ConversationStatus.OPEN)
        ConversationFactory(workspace=workspace, status=ConversationStatus.CLOSED)

        results = list(
            selectors.conversation_list_for_workspace(workspace=workspace, status="open")
        )

        assert results == [open_conv]

    def test_filters_by_channel(self):
        workspace = WorkspaceFactory()
        web = ConversationFactory(workspace=workspace, channel="web")
        ConversationFactory(workspace=workspace, channel="email")

        results = list(
            selectors.conversation_list_for_workspace(workspace=workspace, channel="web")
        )

        assert results == [web]

    def test_filters_by_customer(self):
        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)
        matching = ConversationFactory(workspace=workspace, customer=customer)
        ConversationFactory(workspace=workspace)

        results = list(
            selectors.conversation_list_for_workspace(workspace=workspace, customer_id=customer.id)
        )

        assert results == [matching]

    def test_unassigned_filter(self):
        workspace = WorkspaceFactory()
        unassigned = ConversationFactory(workspace=workspace)
        membership = WorkspaceMembershipFactory(workspace=workspace)
        ConversationFactory(workspace=workspace, assigned_to=membership)

        results = list(
            selectors.conversation_list_for_workspace(workspace=workspace, unassigned=True)
        )

        assert results == [unassigned]

    def test_assigned_to_filter(self):
        workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(workspace=workspace)
        assigned = ConversationFactory(workspace=workspace, assigned_to=membership)
        ConversationFactory(workspace=workspace)

        results = list(
            selectors.conversation_list_for_workspace(
                workspace=workspace, assigned_to=membership.id
            )
        )

        assert results == [assigned]

    def test_orders_by_last_message_at_descending(self):
        from django.utils import timezone

        workspace = WorkspaceFactory()
        older = ConversationFactory(workspace=workspace, last_message_at=timezone.now())
        newer = ConversationFactory(
            workspace=workspace, last_message_at=timezone.now() + timezone.timedelta(hours=1)
        )

        results = list(selectors.conversation_list_for_workspace(workspace=workspace))

        assert results == [newer, older]


@pytest.mark.django_db
class TestConversationGetForWorkspaceOr404:
    def test_raises_404_for_conversation_in_another_workspace(self):
        workspace = WorkspaceFactory()
        foreign = ConversationFactory()

        with pytest.raises(Http404):
            selectors.conversation_get_for_workspace_or_404(
                workspace=workspace, conversation_id=foreign.id
            )


@pytest.mark.django_db
class TestMessageListForConversation:
    def test_returns_messages_in_chronological_order(self):
        conversation = ConversationFactory()
        first = MessageFactory(conversation=conversation)
        second = MessageFactory(conversation=conversation)

        results = list(selectors.message_list_for_conversation(conversation=conversation))

        assert results == [first, second]

    def test_does_not_include_other_conversations_messages(self):
        conversation = ConversationFactory()
        other = ConversationFactory()
        MessageFactory(conversation=other)

        results = list(selectors.message_list_for_conversation(conversation=conversation))

        assert results == []


@pytest.mark.django_db
class TestMessageGetForWorkspaceOr404:
    def test_returns_a_message_in_scope(self):
        conversation = ConversationFactory()
        message = MessageFactory(conversation=conversation)

        result = selectors.message_get_for_workspace_or_404(
            workspace=conversation.workspace, conversation=conversation, message_id=message.id
        )

        assert result == message

    def test_raises_404_for_a_message_in_another_conversation_same_workspace(self):
        workspace = WorkspaceFactory()
        conversation = ConversationFactory(workspace=workspace)
        other_conversation = ConversationFactory(workspace=workspace)
        foreign_message = MessageFactory(conversation=other_conversation)

        with pytest.raises(Http404):
            selectors.message_get_for_workspace_or_404(
                workspace=workspace, conversation=conversation, message_id=foreign_message.id
            )

    def test_raises_404_for_a_message_in_another_workspace(self):
        conversation = ConversationFactory()
        foreign_message = MessageFactory()

        with pytest.raises(Http404):
            selectors.message_get_for_workspace_or_404(
                workspace=conversation.workspace,
                conversation=conversation,
                message_id=foreign_message.id,
            )
