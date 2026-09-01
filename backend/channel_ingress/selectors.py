"""Tenant-scoped read selectors for channel endpoints and inbound events."""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet
from django.http import Http404

from workspaces.models import Workspace

from .models import ChannelEndpoint, InboundChannelEvent


def endpoint_list_for_workspace(*, workspace: Workspace) -> QuerySet[ChannelEndpoint]:
    return ChannelEndpoint.objects.filter(workspace=workspace).order_by("-created_at")


def endpoint_get_for_workspace(
    *, workspace: Workspace, endpoint_id: UUID | str
) -> ChannelEndpoint | None:
    return ChannelEndpoint.objects.filter(workspace=workspace, pk=endpoint_id).first()


def endpoint_get_for_workspace_or_404(
    *, workspace: Workspace, endpoint_id: UUID | str
) -> ChannelEndpoint:
    endpoint = endpoint_get_for_workspace(workspace=workspace, endpoint_id=endpoint_id)
    if endpoint is None:
        raise Http404("Channel endpoint not found.")
    return endpoint


def inbound_event_list_for_workspace(*, workspace: Workspace) -> QuerySet[InboundChannelEvent]:
    return (
        InboundChannelEvent.objects.filter(workspace=workspace)
        .select_related("endpoint")
        .order_by("-created_at")
    )


def inbound_event_get_for_workspace(
    *, workspace: Workspace, event_id: UUID | str
) -> InboundChannelEvent | None:
    return InboundChannelEvent.objects.filter(workspace=workspace, pk=event_id).first()
