"""Shared cross-tenant/RBAC adversarial fixture (Phase 15 checkpoint 3, Part
A). Every domain's ``test_cross_tenant_matrix.py`` builds the same shape of
scenario — two workspaces, a full role ladder in one of them, and one
foreign owner — so this module is the one shared place that shape is built,
while each app's test file still writes its own domain-specific URLs and
expected behavior (no generic assertion framework lives here — see the
Phase 15 brief, Part A, section 2: a shared fixture is fine, a framework
that obscures domain semantics is not).

Not a pytest fixture module in its own right (no ``conftest.py`` role) —
each test file imports :func:`two_workspaces` directly as a plain
``@pytest.fixture``-decorated function, exactly like the existing
``workspaces/tests/test_cross_tenant_matrix.py`` pattern.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from workspaces.models import WorkspaceRole
from workspaces.tests.factories import UserFactory, WorkspaceFactory, WorkspaceMembershipFactory


@pytest.fixture
def two_workspaces():
    """Workspace A with a full role ladder (owner/admin/support_agent/
    viewer) plus Workspace B with its own owner — the actor set the Phase
    15 brief specifies (A_OWNER, A_ADMIN, A_SUPPORT_AGENT, A_VIEWER,
    B_OWNER)."""
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()

    a_owner = WorkspaceMembershipFactory(workspace=workspace_a, role=WorkspaceRole.OWNER)
    a_admin = WorkspaceMembershipFactory(workspace=workspace_a, role=WorkspaceRole.ADMIN)
    a_agent = WorkspaceMembershipFactory(workspace=workspace_a, role=WorkspaceRole.SUPPORT_AGENT)
    a_viewer = WorkspaceMembershipFactory(workspace=workspace_a, role=WorkspaceRole.VIEWER)
    b_owner = WorkspaceMembershipFactory(workspace=workspace_b, role=WorkspaceRole.OWNER)

    return {
        "workspace_a": workspace_a,
        "workspace_b": workspace_b,
        "a_owner": a_owner,
        "a_admin": a_admin,
        "a_agent": a_agent,
        "a_viewer": a_viewer,
        "b_owner": b_owner,
    }


def api_client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


__all__ = ["two_workspaces", "api_client", "UserFactory"]
