"""Thin Celery boundary for asynchronous inbound-event processing (Phase 13
section 34). Carries only the event id — no payload, credentials, or
provider data crosses this boundary — and delegates entirely to
``channel_ingress.services.process_inbound_channel_event``, which is safe to
invoke more than once for the same event id (see ``claim_inbound_channel_event``).
"""

from __future__ import annotations

from celery import shared_task

from common.tasks import CorrelatedTask


@shared_task(bind=True, base=CorrelatedTask, max_retries=3)
def process_inbound_channel_event_task(self, event_id: str) -> str:
    from .services import process_inbound_channel_event

    return process_inbound_channel_event(event_id)


# ---------------------------------------------------------------------------
# Recovery sweeper Celery Beat task (Phase 13 section 35, mirrors
# ``notifications.tasks.dispatch_due_deliveries_task``)
# ---------------------------------------------------------------------------


@shared_task(bind=True, base=CorrelatedTask, max_retries=0)
def recover_stuck_inbound_events_task(self) -> int:
    from .recovery import recover_stuck_inbound_events

    return recover_stuck_inbound_events()
