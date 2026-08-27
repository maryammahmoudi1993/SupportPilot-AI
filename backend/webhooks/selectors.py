"""Bounded, workspace-scoped read queries for the webhook domain (section
42-45). A foreign workspace's endpoint/delivery resolves to ``None`` (never
raises), matching the 404-on-cross-tenant convention used throughout the
repository (e.g. ``integrations.selectors.connection_get_for_workspace_or_404``).
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from .models import WebhookDelivery, WebhookEndpoint, WebhookEventType


def endpoint_list_for_workspace(*, workspace) -> QuerySet[WebhookEndpoint]:
    return WebhookEndpoint.objects.filter(workspace=workspace).order_by("-created_at")


def endpoint_get_for_workspace(*, workspace, endpoint_id: UUID | str) -> WebhookEndpoint | None:
    return WebhookEndpoint.objects.filter(workspace=workspace, pk=endpoint_id).first()


def active_endpoints_subscribed_to(*, workspace, event_type: str) -> QuerySet[WebhookEndpoint]:
    """Fanout candidate set (section 10): ACTIVE endpoints in this
    workspace subscribed to ``event_type``. ``subscribed_event_types`` is a
    JSON array column — ``contains`` compiles to a Postgres ``@>`` (JSONB
    containment) query, which uses the workspace/status index above plus a
    cheap per-row JSON check rather than an unindexed Python-side filter.
    """
    return WebhookEndpoint.objects.filter(
        workspace=workspace, status="active", subscribed_event_types__contains=[event_type]
    )


def delivery_list_for_workspace(*, workspace) -> QuerySet[WebhookDelivery]:
    return (
        WebhookDelivery.objects.filter(workspace=workspace)
        .select_related("delivery", "endpoint", "event")
        .order_by("-created_at")
    )


def delivery_get_for_workspace(*, workspace, delivery_id: UUID | str) -> WebhookDelivery | None:
    return (
        WebhookDelivery.objects.filter(workspace=workspace, delivery_id=delivery_id)
        .select_related("delivery", "endpoint", "event")
        .first()
    )


def valid_event_types() -> list[str]:
    return [choice.value for choice in WebhookEventType]
