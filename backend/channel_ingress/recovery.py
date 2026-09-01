"""Recovery sweeper for the broker-publish gap (Phase 13 section 35, 62 —
mirrors ``notifications.recovery`` exactly).

``ingest_channel_event`` persists the durable ``InboundChannelEvent`` row and
commits *before* attempting to publish the processing task — if that
best-effort ``transaction.on_commit`` publish is lost (broker outage), the
event would otherwise sit ``RECEIVED`` forever with nothing to ever pick it
back up. This sweep closes that gap the same way Phase 10 Block 4 closed it
for ``Delivery``: a bounded, DB-driven pass that only re-publishes an event
id for the existing claim-then-process boundary
(``channel_ingress.services.process_inbound_channel_event``) to pick up — all
correctness (who actually processes it) comes from that boundary's
transactional claim, never from anything here. Re-publishing the same event
id from two concurrent sweeps, or a sweep racing an already-active worker, is
always safe.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import InboundChannelEvent, InboundChannelEventStatus

logger = logging.getLogger("supportpilot")


def recover_stuck_inbound_events(*, batch_size: int | None = None, now=None) -> int:
    """Re-publish ``RECEIVED`` events older than
    ``CHANNELS_INBOUND_SWEEP_STALE_SECONDS`` (section 35) — a event still
    ``RECEIVED`` well past its own creation time can only mean the original
    publish attempt was lost; one still genuinely in flight is younger than
    the staleness threshold and is left alone."""
    from .tasks import process_inbound_channel_event_task

    batch_size = (
        batch_size if batch_size is not None else settings.CHANNELS_INBOUND_SWEEP_BATCH_SIZE
    )
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.CHANNELS_INBOUND_SWEEP_STALE_SECONDS)
    event_ids = list(
        InboundChannelEvent.objects.filter(
            status=InboundChannelEventStatus.RECEIVED, received_at__lte=cutoff
        )
        .order_by("received_at")
        .values_list("id", flat=True)[:batch_size]
    )
    for event_id in event_ids:
        process_inbound_channel_event_task.delay(str(event_id))
    if event_ids:
        logger.info(
            "channel_ingress_stuck_event_recovered",
            extra={"event": "channel_ingress_stuck_event_recovered", "count": len(event_ids)},
        )
    return len(event_ids)
