"""Real PostgreSQL concurrency for webhook delivery (Phase 10 Block 3,
section 62): two copies of the same Celery task processing one valid claim
must call the transport exactly once — proven with real threads against
real row locks, inherited unchanged from Block 1's claim mechanics."""

from __future__ import annotations

import threading

import django.db as django_db
import pytest

from notifications.models import DeliveryAttempt, DeliveryChannel, DeliveryStatus
from notifications.services import create_delivery, process_claimed_delivery
from webhooks.models import WebhookDelivery
from webhooks.tests.factories import WebhookEndpointFactory, WebhookEventFactory
from webhooks.transport import TransportResult

pytestmark = pytest.mark.django_db(transaction=True)


def test_two_concurrent_task_deliveries_call_transport_only_once(monkeypatch):
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")

    call_count = {"n": 0}
    lock = threading.Lock()

    def fake_transport(**kwargs):
        with lock:
            call_count["n"] += 1
        return TransportResult(status_code=204, latency_ms=1)

    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )

    barrier = threading.Barrier(2)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker():
        django_db.close_old_connections()
        barrier.wait()
        try:
            outcome = process_claimed_delivery(str(delivery.id))
            with results_lock:
                results.append(outcome)
        finally:
            django_db.close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert call_count["n"] == 1
    assert sorted(results) == ["processed", "skipped"]
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1
