"""Tenant-first selectors for every agent-owned resource.

Every lookup filters by ``workspace`` before resolving the object, and every
"get one" helper raises ``Http404`` on a miss so a cross-workspace UUID never
distinguishes "exists in another workspace" from "does not exist".
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.http import Http404

from workspaces.models import Workspace

from .models import AgentDefinition, AgentRun, AgentStep, AgentVersion


def agent_definition_list_for_workspace(
    *, workspace: Workspace, status: str | None = None
) -> QuerySet[AgentDefinition]:
    queryset = AgentDefinition.objects.filter(workspace=workspace)
    if status:
        queryset = queryset.filter(status=status)
    return queryset.order_by("-created_at")


def agent_definition_get_for_workspace_or_404(
    *, workspace: Workspace, agent_id: UUID | str
) -> AgentDefinition:
    definition = AgentDefinition.objects.filter(workspace=workspace, pk=agent_id).first()
    if definition is None:
        raise Http404("Agent not found.")
    return definition


def agent_version_list_for_definition(
    *, workspace: Workspace, agent_definition: AgentDefinition
) -> QuerySet[AgentVersion]:
    return AgentVersion.objects.filter(
        agent_definition=agent_definition, agent_definition__workspace=workspace
    ).order_by("-version")


def agent_version_get_for_workspace_or_404(
    *, workspace: Workspace, agent_definition: AgentDefinition, version_id: UUID | str
) -> AgentVersion:
    version = AgentVersion.objects.filter(
        pk=version_id, agent_definition=agent_definition, agent_definition__workspace=workspace
    ).first()
    if version is None:
        raise Http404("Agent version not found.")
    return version


def agent_run_list_for_workspace(
    *,
    workspace: Workspace,
    status: str | None = None,
    agent_definition_id: UUID | str | None = None,
) -> QuerySet[AgentRun]:
    queryset = AgentRun.objects.filter(workspace=workspace).select_related(
        "agent_version", "agent_version__agent_definition"
    )
    if status:
        queryset = queryset.filter(status=status)
    if agent_definition_id:
        try:
            resolved_id = UUID(str(agent_definition_id))
        except ValueError:
            return queryset.none()
        queryset = queryset.filter(agent_version__agent_definition_id=resolved_id)
    return queryset.order_by("-created_at")


def agent_run_get_for_workspace_or_404(*, workspace: Workspace, run_id: UUID | str) -> AgentRun:
    run = (
        AgentRun.objects.filter(workspace=workspace, pk=run_id)
        .select_related("agent_version", "agent_version__agent_definition")
        .first()
    )
    if run is None:
        raise Http404("Agent run not found.")
    return run


def agent_step_list_for_run(
    *, workspace: Workspace, run: AgentRun, limit: int = 200
) -> QuerySet[AgentStep]:
    """Bounded trace listing — never returns unbounded step history."""
    return AgentStep.objects.filter(workspace=workspace, run=run).order_by("sequence")[:limit]
