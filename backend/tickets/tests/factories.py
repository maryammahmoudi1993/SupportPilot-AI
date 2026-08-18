"""Test factories for tickets."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from customers.tests.factories import CustomerFactory
from tickets.models import Ticket
from workspaces.tests.factories import WorkspaceFactory


class TicketFactory(DjangoModelFactory):
    class Meta:
        model = Ticket

    workspace = factory.SubFactory(WorkspaceFactory)
    customer = factory.SubFactory(CustomerFactory, workspace=factory.SelfAttribute("..workspace"))
    subject = factory.Sequence(lambda n: f"Ticket {n}")
