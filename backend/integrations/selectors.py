"""Tenant-scoped read selectors for integration connections (section 13,
70-73). Every lookup scopes by workspace *before* resolving a specific
connection, so a foreign-workspace connection ID behaves exactly like an ID
that does not exist at all — never a 403 that would confirm existence.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.http import Http404

from workspaces.models import Workspace

from .models import IntegrationConnection


def connection_list_for_workspace(*, workspace: Workspace) -> QuerySet[IntegrationConnection]:
    return IntegrationConnection.objects.filter(workspace=workspace).order_by("provider", "id")


def connection_get_for_workspace_or_404(
    *, workspace: Workspace, connection_id: UUID | str
) -> IntegrationConnection:
    connection = IntegrationConnection.objects.filter(workspace=workspace, pk=connection_id).first()
    if connection is None:
        raise Http404("Integration connection not found.")
    return connection


def resolve_connection_for_tool(
    *, workspace: Workspace, provider: str
) -> IntegrationConnection | None:
    """Server-side connection resolution for a business tool (section 70).

    Never accepts a caller/model-supplied connection identifier — a tool
    handler asks only "does this workspace have an active connection for
    this provider", exactly like ``ToolBinding``/``ToolDefinition``
    resolution in Phase 6. Returns ``None`` (never raises) when no
    connection of this provider exists at all, distinct from "exists but
    disabled" — the tool handler maps each case to its own stable error
    code (``integration_not_configured`` vs. ``integration_disabled``).
    """
    return IntegrationConnection.objects.filter(workspace=workspace, provider=provider).first()
