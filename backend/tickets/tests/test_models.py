"""Ticket model tests: creation, statuses, priorities, and tenancy
invariants."""

import pytest
from django.core.exceptions import ValidationError

from conversations.tests.factories import ConversationFactory
from customers.tests.factories import CustomerFactory
from tickets.models import TicketPriority, TicketStatus
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import TicketFactory


@pytest.mark.django_db
class TestTicketCreation:
    def test_creates_with_defaults(self):
        ticket = TicketFactory()
        assert ticket.status == TicketStatus.OPEN
        assert ticket.priority == TicketPriority.NORMAL
        assert ticket.resolved_at is None

    def test_conversation_is_optional(self):
        ticket = TicketFactory(conversation=None)
        assert ticket.conversation_id is None

    @pytest.mark.parametrize("status", [s.value for s in TicketStatus])
    def test_accepts_every_declared_status(self, status):
        assert TicketFactory(status=status).status == status

    @pytest.mark.parametrize("priority", [p.value for p in TicketPriority])
    def test_accepts_every_declared_priority(self, priority):
        assert TicketFactory(priority=priority).priority == priority


@pytest.mark.django_db
class TestTicketTenancyInvariants:
    def test_customer_from_another_workspace_fails_validation(self):
        workspace = WorkspaceFactory()
        foreign_customer = CustomerFactory(workspace=WorkspaceFactory())
        ticket = TicketFactory.build(workspace=workspace, customer=foreign_customer)

        with pytest.raises(ValidationError):
            ticket.full_clean()

    def test_conversation_from_another_workspace_fails_validation(self):
        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)
        foreign_conversation = ConversationFactory()
        ticket = TicketFactory.build(
            workspace=workspace, customer=customer, conversation=foreign_conversation
        )

        with pytest.raises(ValidationError):
            ticket.full_clean()

    def test_assignee_from_another_workspace_fails_validation(self):
        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)
        foreign_membership = WorkspaceMembershipFactory(workspace=WorkspaceFactory())
        ticket = TicketFactory.build(
            workspace=workspace, customer=customer, assigned_to=foreign_membership
        )

        with pytest.raises(ValidationError):
            ticket.full_clean()

    def test_removed_assignee_leaves_ticket_unassigned(self):
        workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(workspace=workspace)
        ticket = TicketFactory(workspace=workspace, assigned_to=membership)

        membership.delete()
        ticket.refresh_from_db()

        assert ticket.assigned_to_id is None

    def test_conversation_deletion_sets_null_rather_than_deleting_ticket(self):
        workspace = WorkspaceFactory()
        conversation = ConversationFactory(workspace=workspace)
        ticket = TicketFactory(workspace=workspace, conversation=conversation)

        conversation.delete()
        ticket.refresh_from_db()

        assert ticket.conversation_id is None


@pytest.mark.django_db
class TestTicketStringRepresentation:
    def test_str_returns_subject(self):
        ticket = TicketFactory(subject="Broken widget")
        assert str(ticket) == "Broken widget"


@pytest.mark.django_db
class TestTicketResolvedLifecycle:
    def test_resolving_sets_resolved_at(self):
        from django.utils import timezone

        ticket = TicketFactory(status=TicketStatus.OPEN)
        ticket.status = TicketStatus.RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.save()
        assert ticket.resolved_at is not None

    def test_reopening_clears_resolved_at(self):
        from django.utils import timezone

        ticket = TicketFactory(status=TicketStatus.RESOLVED, resolved_at=timezone.now())
        ticket.status = TicketStatus.OPEN
        ticket.resolved_at = None
        ticket.save()
        assert ticket.resolved_at is None
