"""Recovery sweeper tests (Phase 10 Block 4, section 9-22, 38-49): due-work
and expired-claim discovery, broker-outage/broker-return recovery,
concurrency safety across sweepers/claims/reclaims, and abandoned-attempt
semantics.

Uses a throwaway fake channel/handler (mirroring ``test_tasks.py``) so these
tests stay about sweeper/claim plumbing, independent of the real
notification/webhook handlers covered elsewhere.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

import django.db as django_db
import pytest
from django.utils import timezone

import notifications.handlers as handlers_module
import notifications.tasks as tasks_module
from notifications.models import AttemptStatus, DeliveryAttempt, DeliveryStatus
from notifications.recovery import dispatch_due_deliveries, recover_expired_delivery_claims
from notifications.services import (
    claim_delivery,
    complete_delivery_success,
    create_delivery,
)
from notifications.tasks import process_delivery_task
from notifications.tests.factories import DeliveryFactory
from workspaces.tests.factories import WorkspaceFactory

FAKE_CHANNEL = "test_recov_chan"


@pytest.fixture
def fake_channel_calls(monkeypatch):
    """A handler that always succeeds — call-counting only, no network I/O
    (mirrors the sweeper's own no-provider-I/O contract, section 9)."""
    calls: list = []

    def handler(*, delivery, claim_token):
        calls.append((delivery.id, claim_token))
        complete_delivery_success(delivery_id=delivery.id, claim_token=claim_token)

    patched = dict(handlers_module._HANDLERS)
    patched[FAKE_CHANNEL] = handler
    monkeypatch.setattr(handlers_module, "_HANDLERS", patched)
    return calls


def _run_in_threads(*targets):
    threads = [threading.Thread(target=t) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)


# ---------------------------------------------------------------------------
# Due-work discovery (section 9, 38) — sweeper-level, on top of the
# selector-level assertions already in test_selectors.py.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dispatch_due_deliveries_only_publishes_due_pending_and_retry_scheduled(monkeypatch):
    published: list = []
    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing",
        lambda delivery_id, **kwargs: published.append(delivery_id),
    )

    now = timezone.now()
    due_pending = DeliveryFactory(
        status=DeliveryStatus.PENDING, next_attempt_at=now - timedelta(seconds=1)
    )
    due_retry = DeliveryFactory(
        status=DeliveryStatus.RETRY_SCHEDULED, next_attempt_at=now - timedelta(seconds=1)
    )
    DeliveryFactory(status=DeliveryStatus.PENDING, next_attempt_at=now + timedelta(hours=1))
    DeliveryFactory(status=DeliveryStatus.DELIVERED, next_attempt_at=now - timedelta(seconds=1))
    DeliveryFactory(status=DeliveryStatus.FAILED, next_attempt_at=now - timedelta(seconds=1))
    DeliveryFactory(status=DeliveryStatus.DEAD, next_attempt_at=now - timedelta(seconds=1))

    count = dispatch_due_deliveries(now=now)

    assert count == 2
    assert set(published) == {due_pending.id, due_retry.id}


@pytest.mark.django_db
def test_dispatch_due_deliveries_respects_batch_size(monkeypatch):
    published: list = []
    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing",
        lambda delivery_id, **kwargs: published.append(delivery_id),
    )
    now = timezone.now()
    for _ in range(5):
        DeliveryFactory(status=DeliveryStatus.PENDING, next_attempt_at=now - timedelta(seconds=1))

    count = dispatch_due_deliveries(batch_size=2, now=now)

    assert count == 2
    assert len(published) == 2


@pytest.mark.django_db
def test_recover_expired_delivery_claims_only_publishes_expired_claims(monkeypatch):
    import uuid

    published: list = []
    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing",
        lambda delivery_id, **kwargs: published.append(delivery_id),
    )
    now = timezone.now()
    expired = DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=uuid.uuid4(),
        claimed_at=now - timedelta(minutes=10),
        lease_expires_at=now - timedelta(minutes=1),
    )
    DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=uuid.uuid4(),
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )

    count = recover_expired_delivery_claims(now=now)

    assert count == 1
    assert published == [expired.id]


# ---------------------------------------------------------------------------
# Broker outage / broker return (section 12, 20-21, 40)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_initial_broker_failure_then_sweeper_recovery_end_to_end(monkeypatch, fake_channel_calls):
    """Closes the original Phase 10 gap (section 12): a delivery whose only
    publication attempt (the ``transaction.on_commit`` callback) failed
    stays PENDING, unconsumed; the sweeper republishes it later, and once
    the broker is healthy again the delivery progresses to DELIVERED with no
    manual DB repair."""

    def _broker_down(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _broker_down)

    delivery = create_delivery(workspace=WorkspaceFactory(), channel=FAKE_CHANNEL)
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempt_count == 0

    # Sweeper runs while the broker is still down — still fails silently,
    # no domain state mutated, no attempt consumed (section 20).
    count = dispatch_due_deliveries()
    assert count == 1
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempt_count == 0
    assert not DeliveryAttempt.objects.filter(delivery=delivery).exists()
    assert len(fake_channel_calls) == 0

    # Broker returns — publication now actually reaches a worker.
    def _broker_up(delivery_id, **kwargs):
        process_delivery_task.apply(args=[delivery_id], kwargs=kwargs).get()

    monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _broker_up)

    dispatch_due_deliveries()

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert len(fake_channel_calls) == 1


@pytest.mark.django_db(transaction=True)
def test_sweeper_broker_failure_never_logs_raw_exception_text(monkeypatch, caplog):
    """Block 2's secret-safe logging regression (section 42, adversarially
    re-proven for Block 4's *new* publication call site): the sweeper's own
    best-effort republish goes through the exact same
    ``dispatch_delivery_for_processing`` -> ``process_delivery_task.delay``
    call as ``create_delivery``'s ``transaction.on_commit`` hook, but this
    exercises it from ``dispatch_due_deliveries`` directly — a call path
    ``test_notification_delivery_dispatch.py``'s equivalent test never
    reaches — so it must be proven independently rather than assumed to
    inherit the earlier guarantee."""
    secret_marker = "SWEEPER_BROKER_SECRET_MARKER_998877"

    def _raise_broker_error(*args, **kwargs):
        raise RuntimeError(f"kombu connection failed: {secret_marker}")

    monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _raise_broker_error)

    # A broker publication failure must mean the Celery task body never
    # runs at all — explicitly guard the provider call it would otherwise
    # reach, so "no network call occurs" is proven, not merely assumed from
    # the delay() exception alone.
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("provider must never be called when publication itself failed")

    monkeypatch.setattr("notifications.notification_delivery.send_notification", _fail_if_called)

    delivery = DeliveryFactory(
        status=DeliveryStatus.PENDING, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )

    with caplog.at_level(logging.DEBUG, logger="supportpilot"):
        count = dispatch_due_deliveries()

    assert count == 1
    assert secret_marker not in caplog.text
    for record in caplog.records:
        assert record.exc_info is None
        assert secret_marker not in record.getMessage()

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempt_count == 0
    assert not DeliveryAttempt.objects.filter(delivery=delivery).exists()


@pytest.mark.django_db(transaction=True)
def test_expired_claim_sweeper_broker_failure_never_logs_raw_exception_text(monkeypatch, caplog):
    """Same adversarial proof as above, for the other new Block 4
    publication call site (``recover_expired_delivery_claims``)."""
    import uuid

    secret_marker = "EXPIRED_CLAIM_SWEEPER_SECRET_MARKER_554433"

    def _raise_broker_error(*args, **kwargs):
        raise RuntimeError(f"kombu connection failed: {secret_marker}")

    monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _raise_broker_error)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("provider must never be called when publication itself failed")

    monkeypatch.setattr("notifications.notification_delivery.send_notification", _fail_if_called)

    now = timezone.now()
    delivery = DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=uuid.uuid4(),
        claimed_at=now - timedelta(minutes=10),
        lease_expires_at=now - timedelta(minutes=1),
    )

    with caplog.at_level(logging.DEBUG, logger="supportpilot"):
        count = recover_expired_delivery_claims()

    assert count == 1
    assert secret_marker not in caplog.text
    for record in caplog.records:
        assert record.exc_info is None
        assert secret_marker not in record.getMessage()

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.CLAIMED
    assert delivery.attempt_count == 0
    assert not DeliveryAttempt.objects.filter(delivery=delivery).exists()


# ---------------------------------------------------------------------------
# Expired-claim recovery through the actual Block 4 recovery path
# (section 14-15, 47) — not just the lower-level Block 1 service directly.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_expired_claim_recovered_through_task_boundary_marks_old_attempt_abandoned(
    fake_channel_calls, monkeypatch
):
    # The sweeper's publication is real best-effort Celery `.delay()` — make
    # it run synchronously here so the test can observe the recovered
    # outcome without a live worker process (mirrors the broker-return half
    # of ``test_initial_broker_failure_then_sweeper_recovery_end_to_end``).
    def _synchronous_delay(delivery_id, **kwargs):
        process_delivery_task.apply(args=[delivery_id], kwargs=kwargs).get()

    monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _synchronous_delay)

    now = timezone.now()
    delivery = DeliveryFactory(channel=FAKE_CHANNEL, next_attempt_at=now - timedelta(minutes=10))
    # Worker A claims with a lease that has already expired by "now".
    _, stale_token = claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)
    delivery.refresh_from_db()
    delivery.lease_expires_at = now - timedelta(seconds=1)
    delivery.save(update_fields=["lease_expires_at"])

    # The recovery sweeper republishes it; process_delivery_task recovers it
    # through reclaim_expired_delivery (section 14), and the abandoned
    # worker's attempt is marked ABANDONED rather than left IN_PROGRESS.
    recover_expired_delivery_claims()

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert len(fake_channel_calls) == 1
    old_attempt = DeliveryAttempt.objects.get(delivery=delivery, claim_token=stale_token)
    assert old_attempt.status == AttemptStatus.ABANDONED
    new_attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=2)
    assert new_attempt.status == AttemptStatus.SUCCEEDED
    assert new_attempt.claim_token != stale_token


# ---------------------------------------------------------------------------
# Concurrency (section 45-48)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_sweepers_publish_same_due_delivery_but_only_one_external_call(fake_channel_calls):
    """Section 45: duplicate task publication from two sweepers is expected
    and safe — only one worker actually gets to run the handler."""
    delivery = DeliveryFactory(
        channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    barrier = threading.Barrier(2)

    def worker():
        django_db.close_old_connections()
        barrier.wait()
        try:
            process_delivery_task.apply(args=[str(delivery.id)]).get()
        finally:
            django_db.close_old_connections()

    _run_in_threads(worker, worker)

    assert len(fake_channel_calls) == 1
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.attempt_count == 1


@pytest.mark.django_db(transaction=True)
def test_sweeper_does_not_disturb_an_actively_claimed_unexpired_delivery(fake_channel_calls):
    """Section 46: a worker already owns a valid claim; the recovery sweeper
    must not reset/reclaim it or produce a second attempt."""
    delivery = DeliveryFactory(
        channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    claimed, token = claim_delivery(delivery_id=delivery.id, lease_seconds=300)

    # Both due-work and expired-claim sweeps run while the claim is active
    # and unexpired — neither should find anything to do.
    assert dispatch_due_deliveries() == 0
    assert recover_expired_delivery_claims() == 0

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.CLAIMED
    assert delivery.claim_token == token
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1
    assert len(fake_channel_calls) == 0


@pytest.mark.django_db(transaction=True)
def test_two_recovery_workers_race_the_same_expired_claim_only_one_progresses(fake_channel_calls):
    """Section 47: through the actual Block 4 recovery path (the Celery task
    boundary, not ``reclaim_expired_delivery`` called directly) — two workers
    racing the same expired claim produce exactly one fresh owner and one
    safe no-op, never a duplicated active reclaim."""
    now = timezone.now()
    delivery = DeliveryFactory(channel=FAKE_CHANNEL, next_attempt_at=now - timedelta(minutes=10))
    claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)
    delivery.refresh_from_db()
    delivery.lease_expires_at = now - timedelta(seconds=1)
    delivery.save(update_fields=["lease_expires_at"])

    barrier = threading.Barrier(2)

    def worker():
        django_db.close_old_connections()
        barrier.wait()
        try:
            process_delivery_task.apply(args=[str(delivery.id)]).get()
        finally:
            django_db.close_old_connections()

    _run_in_threads(worker, worker)

    assert len(fake_channel_calls) == 1
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.attempt_count == 2


@pytest.mark.django_db(transaction=True)
def test_stale_worker_after_recovery_cannot_overwrite_newer_completion_via_task_boundary(
    fake_channel_calls,
):
    """Section 48, exercised through the recovery task boundary rather than
    calling the lower-level service directly (complementing
    ``test_concurrency.py::test_race_stale_worker_cannot_overwrite_newer_completion``)."""
    now = timezone.now()
    delivery = DeliveryFactory(channel=FAKE_CHANNEL, next_attempt_at=now - timedelta(minutes=10))
    _, stale_token = claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)
    delivery.refresh_from_db()
    delivery.lease_expires_at = timezone.now() - timedelta(seconds=1)
    delivery.save(update_fields=["lease_expires_at"])

    # Recovery task reclaims and completes via the fake handler.
    process_delivery_task.apply(args=[str(delivery.id)]).get()
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED

    # Worker A wakes up late and tries to complete with its now-stale token.
    from notifications.errors import StaleClaimError

    with pytest.raises(StaleClaimError):
        complete_delivery_success(delivery_id=delivery.id, claim_token=stale_token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert len(fake_channel_calls) == 1


# ---------------------------------------------------------------------------
# Application restart (section 22, 55): recovery reads only PostgreSQL state
# — nothing here relies on any in-memory queue/list built up over the
# process's lifetime, since these functions are stateless and only ever
# query the database.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_recovery_functions_depend_only_on_database_state(monkeypatch):
    published: list = []
    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing",
        lambda delivery_id, **kwargs: published.append(delivery_id),
    )
    now = timezone.now()
    delivery = DeliveryFactory(
        status=DeliveryStatus.PENDING, next_attempt_at=now - timedelta(seconds=1)
    )

    # A "fresh process" here is simulated by calling the recovery function
    # with no prior in-process setup beyond the database row itself.
    count = dispatch_due_deliveries(now=now)

    assert count == 1
    assert published == [delivery.id]
