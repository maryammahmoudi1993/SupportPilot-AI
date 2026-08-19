"""``customer.lookup``, ``ticket.create``, ``ticket.update`` tool tests
(section 27-29, 53-56, 96, 99)."""

from __future__ import annotations

import pytest

from customers.tests.factories import CustomerFactory
from tickets.models import TicketStatus
from tickets.tests.factories import TicketFactory
from tools.errors import ToolError
from tools.execution import execute_tool

from .factories import bind_tool, running_run


@pytest.mark.django_db(transaction=True)
class TestCustomerLookup:
    def test_lookup_by_id(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        result = execute_tool(
            agent_run=run, tool_key="customer.lookup", arguments={"customer_id": str(customer.id)}
        )
        assert result.output["customer_id"] == str(customer.id)

    def test_lookup_by_email(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        customer = CustomerFactory(workspace=run.workspace, email="a@example.com")
        result = execute_tool(
            agent_run=run, tool_key="customer.lookup", arguments={"email": "a@example.com"}
        )
        assert result.output["customer_id"] == str(customer.id)

    def test_lookup_by_external_reference(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        customer = CustomerFactory(workspace=run.workspace, external_id="crm-123")
        result = execute_tool(
            agent_run=run, tool_key="customer.lookup", arguments={"external_reference": "crm-123"}
        )
        assert result.output["customer_id"] == str(customer.id)

    def test_not_found(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run, tool_key="customer.lookup", arguments={"email": "nobody@example.com"}
            )
        assert exc_info.value.code == "customer_not_found"

    def test_cross_workspace_id_behaves_like_not_found(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        foreign_customer = CustomerFactory()  # different workspace
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="customer.lookup",
                arguments={"customer_id": str(foreign_customer.id)},
            )
        assert exc_info.value.code == "customer_not_found"

    def test_no_identifier_rejected(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(agent_run=run, tool_key="customer.lookup", arguments={})
        assert exc_info.value.code == "tool_invalid_input"

    def test_two_identifiers_rejected(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="customer.lookup",
                arguments={"email": "a@example.com", "external_reference": "x"},
            )
        assert exc_info.value.code == "tool_invalid_input"

    def test_invalid_customer_id_format_is_not_found_not_a_crash(self):
        run = running_run()
        bind_tool(run, "customer.lookup")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run, tool_key="customer.lookup", arguments={"customer_id": "not-a-uuid"}
            )
        assert exc_info.value.code == "customer_not_found"


@pytest.mark.django_db(transaction=True)
class TestTicketCreate:
    def test_success(self):
        run = running_run()
        bind_tool(run, "ticket.create")
        customer = CustomerFactory(workspace=run.workspace)
        result = execute_tool(
            agent_run=run,
            tool_key="ticket.create",
            arguments={"customer_id": str(customer.id), "subject": "Order missing"},
        )
        assert result.output["status"] == "open"
        assert result.output["subject"] == "Order missing"

    def test_foreign_customer_rejected(self):
        run = running_run()
        bind_tool(run, "ticket.create")
        foreign_customer = CustomerFactory()
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="ticket.create",
                arguments={"customer_id": str(foreign_customer.id), "subject": "x"},
            )
        assert exc_info.value.code == "customer_not_found"

    def test_invalid_priority_rejected(self):
        run = running_run()
        bind_tool(run, "ticket.create")
        customer = CustomerFactory(workspace=run.workspace)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="ticket.create",
                arguments={
                    "customer_id": str(customer.id),
                    "subject": "x",
                    "priority": "not-a-real-priority",
                },
            )
        assert exc_info.value.code == "tool_invalid_input"

    def test_valid_priority_is_applied(self):
        run = running_run()
        bind_tool(run, "ticket.create")
        customer = CustomerFactory(workspace=run.workspace)
        result = execute_tool(
            agent_run=run,
            tool_key="ticket.create",
            arguments={"customer_id": str(customer.id), "subject": "x", "priority": "high"},
        )
        assert result.output["priority"] == "high"

    def test_audit_actor_is_derived_from_the_agent_runs_creator(self):
        from accounts.tests.factories import UserFactory

        run = running_run()
        run.created_by = UserFactory()
        run.save(update_fields=["created_by"])
        bind_tool(run, "ticket.create")
        customer = CustomerFactory(workspace=run.workspace)
        result = execute_tool(
            agent_run=run,
            tool_key="ticket.create",
            arguments={"customer_id": str(customer.id), "subject": "x"},
        )
        assert result.output["subject"] == "x"


@pytest.mark.django_db(transaction=True)
class TestTicketUpdate:
    def test_status_transition(self):
        run = running_run()
        bind_tool(run, "ticket.update")
        ticket = TicketFactory(workspace=run.workspace, status=TicketStatus.OPEN)
        result = execute_tool(
            agent_run=run,
            tool_key="ticket.update",
            arguments={"ticket_id": str(ticket.id), "status": TicketStatus.RESOLVED},
        )
        assert result.output["status"] == TicketStatus.RESOLVED

    def test_invalid_transition_rejected(self):
        run = running_run()
        bind_tool(run, "ticket.update")
        ticket = TicketFactory(workspace=run.workspace, status=TicketStatus.CLOSED)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="ticket.update",
                arguments={"ticket_id": str(ticket.id), "status": TicketStatus.RESOLVED},
            )
        assert exc_info.value.code == "integration_invalid_request"

    def test_priority_only_update(self):
        run = running_run()
        bind_tool(run, "ticket.update")
        ticket = TicketFactory(workspace=run.workspace)
        result = execute_tool(
            agent_run=run,
            tool_key="ticket.update",
            arguments={"ticket_id": str(ticket.id), "priority": "urgent"},
        )
        assert result.output["priority"] == "urgent"

    def test_foreign_ticket_is_not_found(self):
        run = running_run()
        bind_tool(run, "ticket.update")
        foreign_ticket = TicketFactory()
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="ticket.update",
                arguments={"ticket_id": str(foreign_ticket.id), "priority": "high"},
            )
        assert exc_info.value.code == "ticket_not_found"

    def test_invalid_ticket_id_format_is_not_found_not_a_crash(self):
        run = running_run()
        bind_tool(run, "ticket.update")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="ticket.update",
                arguments={"ticket_id": "not-a-uuid", "priority": "high"},
            )
        assert exc_info.value.code == "ticket_not_found"

    def test_note_is_appended_not_overwritten(self):
        run = running_run()
        bind_tool(run, "ticket.update")
        ticket = TicketFactory(workspace=run.workspace, description="Original description")
        execute_tool(
            agent_run=run,
            tool_key="ticket.update",
            arguments={"ticket_id": str(ticket.id), "note": "Agent left a note"},
        )
        ticket.refresh_from_db()
        assert "Original description" in ticket.description
        assert "Agent left a note" in ticket.description
