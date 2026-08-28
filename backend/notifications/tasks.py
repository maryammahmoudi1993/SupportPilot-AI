"""Thin Celery boundary for delivery processing (Phase 10 Block 1, section
19). The task carries only the delivery identifier and immediately delegates
to the service layer — no payload, credentials, recipient data, or ORM
serialization ever crosses this boundary, and no domain logic (claim
eligibility, retry/terminal decisions) lives here.
"""

from __future__ import annotations

from celery import shared_task


@shared_task(bind=True, max_retries=0)
def process_delivery_task(self, delivery_id: str) -> str:
    from .services import process_claimed_delivery

    return process_claimed_delivery(delivery_id)


# ---------------------------------------------------------------------------
# Recovery sweeper Celery Beat tasks (Phase 10 Block 4, section 17-19)
# ---------------------------------------------------------------------------
#
# Both tasks carry zero domain logic (section 17, matching the rule above):
# each delegates entirely to ``notifications.recovery``, which only
# re-publishes delivery ids — never performs provider/HTTP I/O itself. Both
# are safe to run from more than one Beat scheduler at the same time
# (section 19): duplicate publication is expected and harmless, since only
# the claim/reclaim primitives inside ``process_delivery_task`` actually
# decide ownership.


@shared_task(bind=True, max_retries=0)
def dispatch_due_deliveries_task(self) -> int:
    from .recovery import dispatch_due_deliveries

    return dispatch_due_deliveries()


@shared_task(bind=True, max_retries=0)
def recover_expired_delivery_claims_task(self) -> int:
    from .recovery import recover_expired_delivery_claims

    return recover_expired_delivery_claims()
