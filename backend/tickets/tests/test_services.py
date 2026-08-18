"""Ticket service tests: creation, assignment rules, and status lifecycle."""

import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError

from audit.models import AuditEvent
from customers.tests.factories import CustomerFactory
from tickets import services
from tickets.models import TicketStatus
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import TicketFactory


@pytest.mark.django_db
class TestCreateTicket:
    def test_creates_ticket_for_customer(self):
        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)

        ticket = services.create_ticket(workspace=workspace, customer=customer, subject="Help")

        assert ticket.workspace_id == workspace.id
        assert ticket.status == TicketStatus.OPEN

    def test_foreign_customer_is_rejected(self):
        workspace = WorkspaceFactory()
        foreign_customer = CustomerFactory(workspace=WorkspaceFactory())

        with pytest.raises(ValidationError):
            services.create_ticket(workspace=workspace, customer=foreign_customer, subject="Help")

    def test_foreign_conversation_is_rejected(self):
        from conversations.tests.factories import ConversationFactory

        workspace = WorkspaceFactory()
        customer = CustomerFactory(workspace=workspace)
        foreign_conversation = ConversationFactory()

        with pytest.raises(ValidationError):
            services.create_ticket(
                workspace=workspace,
                customer=customer,
                subject="Help",
                conversation=foreign_conversation,
            )


@pytest.mark.django_db
class TestUpdateTicket:
    def test_manager_can_update_any_ticket(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        ticket = TicketFactory(workspace=workspace)

        updated = services.update_ticket(
            workspace=workspace, ticket=ticket, actor_membership=manager, data={"subject": "New"}
        )

        assert updated.subject == "New"

    def test_agent_can_update_ticket_assigned_to_them(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, assigned_to=agent)

        updated = services.update_ticket(
            workspace=workspace, ticket=ticket, actor_membership=agent, data={"subject": "New"}
        )

        assert updated.subject == "New"

    def test_agent_cannot_update_ticket_not_assigned_to_them(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace)

        with pytest.raises(PermissionDenied):
            services.update_ticket(
                workspace=workspace, ticket=ticket, actor_membership=agent, data={"subject": "New"}
            )


@pytest.mark.django_db
class TestAssignTicket:
    def test_manager_can_assign_to_any_member(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace)

        updated = services.assign_ticket(
            workspace=workspace,
            actor=manager.user,
            actor_membership=manager,
            ticket=ticket,
            target_membership=agent,
        )

        assert updated.assigned_to_id == agent.id
        assert AuditEvent.objects.filter(action="ticket.assigned").exists()

    def test_agent_can_self_assign_unassigned_ticket(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace)

        updated = services.self_assign_ticket(
            workspace=workspace, actor=agent.user, actor_membership=agent, ticket=ticket
        )

        assert updated.assigned_to_id == agent.id

    def test_agent_cannot_assign_to_a_peer(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        peer = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace)

        with pytest.raises(PermissionDenied):
            services.assign_ticket(
                workspace=workspace,
                actor=agent.user,
                actor_membership=agent,
                ticket=ticket,
                target_membership=peer,
            )

    def test_agent_cannot_reassign_a_ticket_already_assigned_to_someone_else(self):
        workspace = WorkspaceFactory()
        first_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        second_agent = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        ticket = TicketFactory(workspace=workspace, assigned_to=first_agent)

        with pytest.raises(PermissionDenied):
            services.assign_ticket(
                workspace=workspace,
                actor=second_agent.user,
                actor_membership=second_agent,
                ticket=ticket,
                target_membership=second_agent,
            )

    def test_foreign_target_membership_is_rejected(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        foreign_membership = WorkspaceMembershipFactory(workspace=WorkspaceFactory())
        ticket = TicketFactory(workspace=workspace)

        with pytest.raises(ValidationError):
            services.assign_ticket(
                workspace=workspace,
                actor=manager.user,
                actor_membership=manager,
                ticket=ticket,
                target_membership=foreign_membership,
            )

    def test_manager_can_unassign(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, assigned_to=agent)

        updated = services.unassign_ticket(
            workspace=workspace, actor=manager.user, actor_membership=manager, ticket=ticket
        )

        assert updated.assigned_to_id is None

    def test_agent_cannot_unassign(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, assigned_to=agent)

        with pytest.raises(PermissionDenied):
            services.unassign_ticket(
                workspace=workspace, actor=agent.user, actor_membership=agent, ticket=ticket
            )


@pytest.mark.django_db
class TestTicketStatusLifecycle:
    def test_resolving_sets_resolved_at_and_records_audit(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        ticket = TicketFactory(workspace=workspace, status=TicketStatus.OPEN)

        updated = services.resolve_ticket(
            workspace=workspace, actor=manager.user, actor_membership=manager, ticket=ticket
        )

        assert updated.status == TicketStatus.RESOLVED
        assert updated.resolved_at is not None
        assert AuditEvent.objects.filter(action="ticket.resolved").exists()

    def test_reopening_resolved_ticket_clears_resolved_at(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        ticket = TicketFactory(workspace=workspace, status=TicketStatus.OPEN)
        ticket = services.resolve_ticket(
            workspace=workspace, actor=manager.user, actor_membership=manager, ticket=ticket
        )

        updated = services.reopen_ticket(
            workspace=workspace, actor=manager.user, actor_membership=manager, ticket=ticket
        )

        assert updated.status == TicketStatus.OPEN
        assert updated.resolved_at is None
        assert AuditEvent.objects.filter(action="ticket.reopened").exists()

    def test_invalid_transition_from_closed_is_rejected(self):
        workspace = WorkspaceFactory()
        manager = WorkspaceMembershipFactory(
            workspace=workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        ticket = TicketFactory(workspace=workspace, status=TicketStatus.CLOSED)

        with pytest.raises(ValidationError):
            services.change_ticket_status(
                workspace=workspace,
                actor=manager.user,
                actor_membership=manager,
                ticket=ticket,
                new_status=TicketStatus.IN_PROGRESS,
            )

    def test_agent_cannot_change_status_of_unassigned_ticket(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, status=TicketStatus.OPEN)

        with pytest.raises(PermissionDenied):
            services.change_ticket_status(
                workspace=workspace,
                actor=agent.user,
                actor_membership=agent,
                ticket=ticket,
                new_status=TicketStatus.IN_PROGRESS,
            )

    def test_agent_can_change_status_of_ticket_assigned_to_them(self):
        workspace = WorkspaceFactory()
        agent = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.SUPPORT_AGENT)
        ticket = TicketFactory(workspace=workspace, status=TicketStatus.OPEN, assigned_to=agent)

        updated = services.change_ticket_status(
            workspace=workspace,
            actor=agent.user,
            actor_membership=agent,
            ticket=ticket,
            new_status=TicketStatus.IN_PROGRESS,
        )

        assert updated.status == TicketStatus.IN_PROGRESS

    def test_viewer_cannot_change_status(self):
        workspace = WorkspaceFactory()
        viewer = WorkspaceMembershipFactory(workspace=workspace, role=WorkspaceRole.VIEWER)
        ticket = TicketFactory(workspace=workspace, status=TicketStatus.OPEN)

        with pytest.raises(PermissionDenied):
            services.change_ticket_status(
                workspace=workspace,
                actor=viewer.user,
                actor_membership=viewer,
                ticket=ticket,
                new_status=TicketStatus.IN_PROGRESS,
            )
