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


def test_recovery_after_the_event_is_actually_processed_is_a_true_noop(monkeypatch):
    """Phase 16 Part B, section 16: run the sweeper, let the real claim
    boundary process the event it re-published, then run the sweeper
    again — the second sweep must find nothing left to recover. This is
    the module's own documented invariant (all correctness lives in
    ``process_inbound_channel_event``'s claim, never in the sweep) proven
    end-to-end rather than just asserted in the docstring."""
    from channel_ingress.services import claim_inbound_channel_event, mark_event_processed

    published = []
    monkeypatch.setattr(
        "channel_ingress.tasks.process_inbound_channel_event_task.delay",
        lambda event_id: published.append(event_id),
    )
    event = InboundChannelEventFactory(status=InboundChannelEventStatus.RECEIVED)
    InboundChannelEvent.objects.filter(pk=event.pk).update(
        received_at=timezone.now() - timezone.timedelta(seconds=3600)
    )

    first_pass = recover_stuck_inbound_events(now=timezone.now())
    assert first_pass == 1
    assert published == [str(event.id)]

    # The re-published task runs for real through the actual claim
    # boundary (not just a status-flag flip), reaching a genuine terminal
    # state exactly like the production worker would.
    claimed = claim_inbound_channel_event(event.id)
    assert claimed is not None
    mark_event_processed(event=claimed, conversation=None, message=None)

    second_pass = recover_stuck_inbound_events(now=timezone.now())

    assert second_pass == 0
    assert published == [str(event.id)]  # no second dispatch


def test_recovery_run_twice_before_processing_republishes_but_never_double_processes(
    monkeypatch,
):
    """The sweep itself carries no claim of its own — it may legitimately
    re-publish the same still-``RECEIVED`` event twice if two sweeps race
    ahead of any worker actually processing it (documented at-least-once
    republish). What must never happen is a second logical processing:
    the real claim boundary still only lets one of the two republished
    tasks through."""
    from channel_ingress.services import claim_inbound_channel_event

    published = []
    monkeypatch.setattr(
        "channel_ingress.tasks.process_inbound_channel_event_task.delay",
        lambda event_id: published.append(event_id),
    )
    event = InboundChannelEventFactory(status=InboundChannelEventStatus.RECEIVED)
    InboundChannelEvent.objects.filter(pk=event.pk).update(
        received_at=timezone.now() - timezone.timedelta(seconds=3600)
    )

    recover_stuck_inbound_events(now=timezone.now())
    recover_stuck_inbound_events(now=timezone.now())

    # Both sweeps re-published (the sweep itself is not the dedupe point).
    assert published == [str(event.id), str(event.id)]

    # But only one of the two redelivered tasks can ever actually claim
    # the event — the second observes it already PROCESSING/terminal.
    first_claim = claim_inbound_channel_event(event.id)
    second_claim = claim_inbound_channel_event(event.id)
    assert first_claim is not None
    assert second_claim is None
