"""Ticket selector tests: tenant isolation, filtering, and priority
ordering."""

import pytest
from django.http import Http404

from customers.tests.factories import CustomerFactory
from tickets import selectors
from tickets.models import TicketPriority, TicketStatus
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import TicketFactory


@pytest.mark.django_db
class TestTicketListForWorkspace:
    def test_only_returns_tickets_in_the_given_workspace(self):
        workspace_a = WorkspaceFactory()
        in_a = TicketFactory(workspace=workspace_a)
        TicketFactory()

        results = list(selectors.ticket_list_for_workspace(workspace=workspace_a))

        assert results == [in_a]

    def test_filters_by_status(self):
        workspace = WorkspaceFactory()
        open_ticket = TicketFactory(workspace=workspace, status=TicketStatus.OPEN)
        TicketFactory(workspace=workspace, status=TicketStatus.CLOSED)

        results = list(selectors.ticket_list_for_workspace(workspace=workspace, status="open"))

        assert results == [open_ticket]

    def test_filters_by_customer(self):
        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)
        matching = TicketFactory(workspace=workspace, customer=customer)
        TicketFactory(workspace=workspace)

        results = list(
            selectors.ticket_list_for_workspace(workspace=workspace, customer_id=customer.id)
        )

        assert results == [matching]

    def test_unassigned_filter(self):
        workspace = WorkspaceFactory()
        unassigned = TicketFactory(workspace=workspace)
        membership = WorkspaceMembershipFactory(workspace=workspace)
        TicketFactory(workspace=workspace, assigned_to=membership)

        results = list(selectors.ticket_list_for_workspace(workspace=workspace, unassigned=True))

        assert results == [unassigned]

    def test_assigned_to_filter(self):
        workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(workspace=workspace)
        assigned = TicketFactory(workspace=workspace, assigned_to=membership)
        TicketFactory(workspace=workspace)

        results = list(
            selectors.ticket_list_for_workspace(workspace=workspace, assigned_to=membership.id)
        )

        assert results == [assigned]

    def test_filters_by_conversation(self):
        from conversations.tests.factories import ConversationFactory

        workspace = WorkspaceFactory()
        conversation = ConversationFactory(workspace=workspace)
        matching = TicketFactory(workspace=workspace, conversation=conversation)
        TicketFactory(workspace=workspace)

        results = list(
            selectors.ticket_list_for_workspace(
                workspace=workspace, conversation_id=conversation.id
            )
        )

        assert results == [matching]

    def test_urgent_and_high_priority_sort_first(self):
        workspace = WorkspaceFactory()
        low = TicketFactory(workspace=workspace, priority=TicketPriority.LOW)
        urgent = TicketFactory(workspace=workspace, priority=TicketPriority.URGENT)
        normal = TicketFactory(workspace=workspace, priority=TicketPriority.NORMAL)
        high = TicketFactory(workspace=workspace, priority=TicketPriority.HIGH)

        results = list(selectors.ticket_list_for_workspace(workspace=workspace))

        assert results == [urgent, high, normal, low]


@pytest.mark.django_db
class TestTicketGetForWorkspaceOr404:
    def test_raises_404_for_ticket_in_another_workspace(self):
        workspace = WorkspaceFactory()
        foreign = TicketFactory()

        with pytest.raises(Http404):
            selectors.ticket_get_for_workspace_or_404(workspace=workspace, ticket_id=foreign.id)
