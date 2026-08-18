"""Test factories for customers."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from customers.models import Customer
from workspaces.tests.factories import WorkspaceFactory


class CustomerFactory(DjangoModelFactory):
    class Meta:
        model = Customer

    workspace = factory.SubFactory(WorkspaceFactory)
    first_name = "Jane"
    last_name = "Doe"
    email = factory.Sequence(lambda n: f"customer{n}@example.com")
    is_active = True
