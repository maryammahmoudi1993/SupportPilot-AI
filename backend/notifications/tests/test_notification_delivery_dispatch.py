"""Transactional dispatch tests (Phase 10 Block 2, section 9-10, 31-32):
broker publication failure must never lose or corrupt a committed delivery,
and two concurrent deliveries of the same Celery task must call the
provider exactly once. Both require real commits (``transaction=True``) —
one for ``transaction.on_commit`` to actually fire, the other for real
PostgreSQL row locking across real threads.
"""

from __future__ import annotations

import threading

import django.db as django_db
import pytest

import notifications.tasks as tasks_module
from integrations.models import IntegrationProvider
from integrations.providers.fakes import FakeNotificationProvider
from integrations.tests.factories import IntegrationConnectionFactory
from notifications.models import Delivery, DeliveryAttempt, DeliveryChannel, DeliveryStatus
from notifications.notification_delivery import create_or_reuse_notification_delivery
from notifications.services import create_delivery, process_claimed_delivery
from tools.tests.factories import ToolExecutionFactory

pytestmark = pytest.mark.django_db(transaction=True)


def test_broker_publication_failure_leaves_delivery_recoverable(monkeypatch):
    def _raise_broker_error(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _raise_broker_error)

    tool_execution = ToolExecutionFactory()
    workspace = tool_execution.workspace
    delivery = create_delivery(workspace=workspace, channel=DeliveryChannel.NOTIFICATION)

    # The commit already happened — the broker failure must not roll it
    # back, delete it, mark it failed, or consume an attempt slot.
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempt_count == 0
    assert delivery.last_error_code == ""
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 0

    # Still fully recoverable: a later worker (or Block 4's sweeper) can
    # claim it normally.
    from notifications.services import claim_delivery

    claimed, _token = claim_delivery(delivery_id=delivery.id)
    assert claimed.status == DeliveryStatus.CLAIMED


def test_two_concurrent_task_deliveries_call_provider_only_once(monkeypatch):
    tool_execution = ToolExecutionFactory()
    workspace = tool_execution.workspace
    IntegrationConnectionFactory(workspace=workspace, provider=IntegrationProvider.EMAIL)
    fake = FakeNotificationProvider()
    monkeypatch.setattr("integrations.services.get_notification_provider", lambda provider: fake)

    notification_delivery = create_or_reuse_notification_delivery(
        tool_execution=tool_execution,
        workspace=workspace,
        recipient_email="a@example.com",
        subject="s",
        body="b",
    )
    delivery_id = notification_delivery.delivery_id

    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def worker():
        django_db.close_old_connections()
        barrier.wait()
        try:
            outcome = process_claimed_delivery(str(delivery_id))
            with lock:
                results.append(outcome)
        finally:
            django_db.close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert fake.send_call_count == 1
    assert sorted(results) == ["processed", "skipped"]
    delivery = Delivery.objects.get(pk=delivery_id)
    assert delivery.status == DeliveryStatus.DELIVERED
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1
