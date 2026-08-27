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
