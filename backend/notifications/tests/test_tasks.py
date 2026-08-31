"""Celery boundary tests (section 19-20, 25; Block 2 section 4, 14): the
task calls the service and carries no domain logic; a duplicate task
delivery never creates a second simultaneously active attempt; a genuinely
unregistered channel is skipped without consuming a claim/attempt slot
(replacing Block 1's placeholder dead-lettering, which is no longer
acceptable now that a real producer — ``notification.send`` — exists).

Uses a throwaway fake channel/handler (monkeypatched into the registry) so
these tests stay about task/claim plumbing, independent of the real
notification handler covered in ``test_notification_delivery.py``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

import notifications.handlers as handlers_module
from notifications.models import DeliveryAttempt, DeliveryStatus
from notifications.services import complete_delivery_success
from notifications.tasks import (
    dispatch_due_deliveries_task,
    process_delivery_task,
    recover_expired_delivery_claims_task,
)
from notifications.tests.factories import DeliveryFactory

pytestmark = pytest.mark.django_db

FAKE_CHANNEL = "test_fake_channel"


@pytest.fixture
def fake_channel_calls(monkeypatch):
    calls: list[tuple] = []

    def handler(*, delivery, claim_token):
        calls.append((delivery.id, claim_token))
        complete_delivery_success(delivery_id=delivery.id, claim_token=claim_token)

    patched = dict(handlers_module._HANDLERS)
    patched[FAKE_CHANNEL] = handler
    monkeypatch.setattr(handlers_module, "_HANDLERS", patched)
    return calls


def test_task_calls_registered_handler_which_completes_the_delivery(fake_channel_calls):
    delivery = DeliveryFactory(
        channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    result = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert result == "processed"
    assert len(fake_channel_calls) == 1
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED


def test_duplicate_task_delivery_is_a_safe_no_op(fake_channel_calls):
    delivery = DeliveryFactory(
        channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    first = process_delivery_task.apply(args=[str(delivery.id)]).get()
    second = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert first == "processed"
    assert second == "skipped"
    assert len(fake_channel_calls) == 1
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1


def test_unsupported_channel_is_skipped_without_consuming_an_attempt():
    delivery = DeliveryFactory(
        channel="unregistered_chan", next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    result = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert result == "skipped_unsupported_channel"
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempt_count == 0
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 0


def test_task_on_unclaimable_delivery_skips_safely():
    delivery = DeliveryFactory(status=DeliveryStatus.DELIVERED)
    result = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert result == "skipped"


# ---------------------------------------------------------------------------
# Recovery sweeper Celery Beat task bodies (Phase 10 Block 4, section 17)
# ---------------------------------------------------------------------------


def test_dispatch_due_deliveries_task_delegates_to_recovery_service(monkeypatch):
    published: list = []
    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing",
        lambda delivery_id, **kwargs: published.append(delivery_id),
    )
    delivery = DeliveryFactory(next_attempt_at=timezone.now() - timedelta(seconds=1))
    result = dispatch_due_deliveries_task.apply().get()
    assert result == 1
    assert published == [delivery.id]


def test_recover_expired_delivery_claims_task_delegates_to_recovery_service(monkeypatch):
    import uuid

    published: list = []
    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing",
        lambda delivery_id, **kwargs: published.append(delivery_id),
    )
    now = timezone.now()
    delivery = DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=uuid.uuid4(),
        claimed_at=now - timedelta(minutes=10),
        lease_expires_at=now - timedelta(minutes=1),
    )
    result = recover_expired_delivery_claims_task.apply().get()
    assert result == 1
    assert published == [delivery.id]
