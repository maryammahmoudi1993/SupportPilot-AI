"""Dedup, idempotency-conflict, and channel/tenant isolation for
``ingest_channel_event`` (Phase 13 section 11-12, 29, 60)."""

from __future__ import annotations

import pytest

from channel_ingress.errors import IdempotencyConflictError
from channel_ingress.models import InboundChannelEvent, InboundChannelEventStatus
from channel_ingress.services import ingest_channel_event
from channel_ingress.tests.factories import ChannelEndpointFactory

pytestmark = pytest.mark.django_db


def _ingest(endpoint, **overrides):
    kwargs = dict(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="customer@example.com",
        body="hello",
    )
    kwargs.update(overrides)
    return ingest_channel_event(**kwargs)


def test_first_ingest_creates_a_received_event():
    endpoint = ChannelEndpointFactory()
    event = _ingest(endpoint)
    assert event.status == InboundChannelEventStatus.RECEIVED
    assert InboundChannelEvent.objects.filter(endpoint=endpoint).count() == 1


def test_duplicate_delivery_same_payload_is_idempotent():
    endpoint = ChannelEndpointFactory()
    first = _ingest(endpoint)
    second = _ingest(endpoint)
    assert first.id == second.id
    assert InboundChannelEvent.objects.filter(endpoint=endpoint).count() == 1


def test_duplicate_event_id_different_payload_is_a_conflict():
    endpoint = ChannelEndpointFactory()
    _ingest(endpoint)
    with pytest.raises(IdempotencyConflictError):
        _ingest(endpoint, payload_digest="digest-b", body="different content")


def test_same_provider_event_id_on_different_endpoints_does_not_collide():
    """Section 29: a provider event id must never collide across different
    channel endpoints, even in the same workspace."""
    endpoint_a = ChannelEndpointFactory()
    endpoint_b = ChannelEndpointFactory(workspace=endpoint_a.workspace)
    event_a = _ingest(endpoint_a)
    event_b = _ingest(endpoint_b)
    assert event_a.id != event_b.id


def test_same_provider_event_id_across_workspaces_does_not_collide():
    endpoint_a = ChannelEndpointFactory()
    endpoint_b = ChannelEndpointFactory()
    event_a = _ingest(endpoint_a)
    event_b = _ingest(endpoint_b)
    assert event_a.id != event_b.id
    assert event_a.workspace_id != event_b.workspace_id
