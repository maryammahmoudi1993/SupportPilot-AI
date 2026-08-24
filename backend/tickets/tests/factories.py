"""Test factories for tickets."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from conversations.tests.factories import ConversationFactory
from customers.tests.factories import CustomerFactory
from tickets.models import HumanHandoff, HumanHandoffReason, Ticket
from workspaces.tests.factories import WorkspaceFactory


class TicketFactory(DjangoModelFactory):
    class Meta:
        model = Ticket

    workspace = factory.SubFactory(WorkspaceFactory)
    customer = factory.SubFactory(CustomerFactory, workspace=factory.SelfAttribute("..workspace"))
    subject = factory.Sequence(lambda n: f"Ticket {n}")


class HumanHandoffFactory(DjangoModelFactory):
    class Meta:
        model = HumanHandoff

    workspace = factory.SubFactory(WorkspaceFactory)
    conversation = factory.SubFactory(
        ConversationFactory, workspace=factory.SelfAttribute("..workspace")
    )
    reason_code = HumanHandoffReason.CUSTOMER_REQUESTED
    safe_summary = "Customer asked to speak with a person."
