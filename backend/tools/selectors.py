"""Tenant-first selectors for every tool-owned resource.

Every "get one" helper filters by workspace (directly, or transitively
through the owning ``AgentVersion``/``AgentRun``) before resolving the
object and raises ``Http404`` on a miss, so a cross-workspace UUID never
distinguishes "exists in another workspace" from "does not exist"
(section 55).
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.http import Http404
from rest_framework.exceptions import ValidationError

from agents.models import AgentVersion
from workspaces.models import Workspace

from .models import ToolBinding, ToolDefinition, ToolExecution


def tool_definition_catalog() -> QuerySet[ToolDefinition]:
    """The full safe tool catalog. Global/code-owned — not workspace-scoped."""
    return ToolDefinition.objects.order_by("key", "id")


def tool_binding_list_for_version(
    *, workspace: Workspace, agent_version: AgentVersion
) -> QuerySet[ToolBinding]:
    return (
        ToolBinding.objects.filter(
            agent_version=agent_version, agent_version__agent_definition__workspace=workspace
        )
        .select_related("tool_definition")
        .order_by("-created_at", "-id")
    )


def tool_binding_get_for_workspace_or_404(
    *, workspace: Workspace, agent_version: AgentVersion, binding_id: UUID | str
) -> ToolBinding:
    binding = (
        ToolBinding.objects.filter(
            pk=binding_id,
            agent_version=agent_version,
            agent_version__agent_definition__workspace=workspace,
        )
        .select_related("tool_definition")
        .first()
    )
    if binding is None:
        raise Http404("Tool binding not found.")
    return binding


def agent_version_get_for_workspace_or_404(
    *, workspace: Workspace, agent_id: UUID | str, version_id: UUID | str
) -> AgentVersion:
    version = AgentVersion.objects.filter(
        pk=version_id,
        agent_definition_id=agent_id if isinstance(agent_id, UUID) else UUID(str(agent_id)),
        agent_definition__workspace=workspace,
    ).first()
    if version is None:
        raise Http404("Agent version not found.")
    return version


def tool_execution_list_for_workspace(
    *,
    workspace: Workspace,
    status: str | None = None,
    agent_run_id: UUID | str | None = None,
) -> QuerySet[ToolExecution]:
    queryset = ToolExecution.objects.filter(workspace=workspace).select_related(
        "tool_definition", "agent_run"
    )
    if status:
        queryset = queryset.filter(status=status)
    if agent_run_id:
        try:
            resolved = UUID(str(agent_run_id))
        except ValueError:
            # Malformed filter must fail predictably (Section 7), not
            # silently look like an honestly-applied filter with no matches.
            raise ValidationError({"agent_run_id": "Must be a valid UUID."}) from None
        queryset = queryset.filter(agent_run_id=resolved)
    return queryset.order_by("-created_at", "-id")


def tool_execution_get_for_workspace_or_404(
    *, workspace: Workspace, execution_id: UUID | str
) -> ToolExecution:
    execution = (
        ToolExecution.objects.filter(workspace=workspace, pk=execution_id)
        .select_related("tool_definition", "agent_run")
        .first()
    )
    if execution is None:
        raise Http404("Tool execution not found.")
    return execution


def resolve_enabled_binding(*, agent_version: AgentVersion, tool_key: str) -> ToolBinding | None:
    """Return the enabled binding for ``tool_key`` on this version, or
    ``None`` if unbound or disabled. Never raises — the execution service
    turns an absent binding into a stable ``ToolNotBoundError``."""
    return (
        ToolBinding.objects.filter(
            agent_version=agent_version,
            tool_definition__key=tool_key,
            enabled=True,
            tool_definition__status="active",
        )
        .select_related("tool_definition")
        .first()
    )
