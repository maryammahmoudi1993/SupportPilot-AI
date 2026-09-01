"""Broker-publish-gap recovery sweeper (Phase 13 section 35, 62)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from channel_ingress.models import InboundChannelEvent, InboundChannelEventStatus
from channel_ingress.recovery import recover_stuck_inbound_events
from channel_ingress.tests.factories import InboundChannelEventFactory

pytestmark = pytest.mark.django_db


def test_a_stale_received_event_is_recovered(monkeypatch):
    published = []
    monkeypatch.setattr(
        "channel_ingress.tasks.process_inbound_channel_event_task.delay",
        lambda event_id: published.append(event_id),
    )
    event = InboundChannelEventFactory(status=InboundChannelEventStatus.RECEIVED)
    InboundChannelEvent.objects.filter(pk=event.pk).update(
        received_at=timezone.now() - timezone.timedelta(seconds=3600)
    )

    recovered_count = recover_stuck_inbound_events(now=timezone.now())

    assert recovered_count == 1
    assert published == [str(event.id)]


def test_a_fresh_received_event_is_left_alone(monkeypatch):
    published = []
    monkeypatch.setattr(
        "channel_ingress.tasks.process_inbound_channel_event_task.delay",
        lambda event_id: published.append(event_id),
    )
    InboundChannelEventFactory(status=InboundChannelEventStatus.RECEIVED)

    recovered_count = recover_stuck_inbound_events(now=timezone.now())

    assert recovered_count == 0
    assert published == []


def test_a_processed_event_is_never_recovered(monkeypatch):
    published = []
    monkeypatch.setattr(
        "channel_ingress.tasks.process_inbound_channel_event_task.delay",
        lambda event_id: published.append(event_id),
    )
    event = InboundChannelEventFactory(status=InboundChannelEventStatus.PROCESSED)
    InboundChannelEvent.objects.filter(pk=event.pk).update(
        received_at=timezone.now() - timezone.timedelta(seconds=3600)
    )

    recovered_count = recover_stuck_inbound_events(now=timezone.now())

    assert recovered_count == 0
    assert published == []
