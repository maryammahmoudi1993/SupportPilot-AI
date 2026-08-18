"""Test factories for workspaces."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from accounts.tests.factories import UserFactory
from workspaces.models import Workspace, WorkspaceMembership, WorkspaceRole


class WorkspaceFactory(DjangoModelFactory):
    class Meta:
        model = Workspace

    name = factory.Sequence(lambda n: f"Workspace {n}")


class WorkspaceMembershipFactory(DjangoModelFactory):
    class Meta:
        model = WorkspaceMembership

    workspace = factory.SubFactory(WorkspaceFactory)
    user = factory.SubFactory(UserFactory)
    role = WorkspaceRole.SUPPORT_AGENT
    is_active = True
