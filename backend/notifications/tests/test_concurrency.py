"""Real PostgreSQL concurrency races (section 26) — actual threads against
actual row locks, mirroring the pattern already used in
``tools/tests/test_execution.py`` and
``agents/tests/test_orchestration_hardening.py``: real ``threading.Thread``s
synchronized with a ``threading.Barrier``, never sequential mocks or
arbitrary ``sleep()`` timing.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import django.db as django_db
import pytest
from django.utils import timezone

from notifications.errors import DeliveryNotClaimableError
from notifications.models import AttemptStatus, DeliveryAttempt, DeliveryStatus
from notifications.services import (
    claim_delivery,
    complete_delivery_success,
    reclaim_expired_delivery,
)
from notifications.tests.factories import DeliveryFactory

pytestmark = pytest.mark.django_db(transaction=True)


def _run_in_threads(*targets):
    threads = [threading.Thread(target=t) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)


# ---------------------------------------------------------------------------
# Race A: two workers claim the same due PENDING delivery simultaneously.
# ---------------------------------------------------------------------------


def test_race_two_workers_claiming_same_pending_delivery():
    delivery = DeliveryFactory(next_attempt_at=timezone.now() - timedelta(seconds=1))
    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []

    def worker():
        django_db.close_old_connections()
        barrier.wait()
        try:
            results.append(claim_delivery(delivery_id=delivery.id))
        except DeliveryNotClaimableError as exc:
            errors.append(exc)
        finally:
            django_db.close_old_connections()

    _run_in_threads(worker, worker)

    assert len(results) == 1, "exactly one worker must win the claim"
    assert len(errors) == 1, "exactly one worker must lose safely"
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.CLAIMED
    assert delivery.attempt_count == 1
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1


# ---------------------------------------------------------------------------
# Race B: Worker A's claim expires, Worker B reclaims and completes, then
# Worker A (stale) attempts to complete — must not overwrite Worker B.
# ---------------------------------------------------------------------------


def test_race_stale_worker_cannot_overwrite_newer_completion():
    now = timezone.now()
    delivery = DeliveryFactory(next_attempt_at=now - timedelta(minutes=10))
    _, stale_token = claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)

    later = now + timedelta(minutes=1)
    reclaimed, fresh_token = reclaim_expired_delivery(delivery_id=delivery.id, now=later)

    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}
    lock = threading.Lock()

    def worker_b_completes():
        django_db.close_old_connections()
        barrier.wait()
        try:
            complete_delivery_success(
                delivery_id=reclaimed.id, claim_token=fresh_token, now=later + timedelta(seconds=1)
            )
            with lock:
                outcomes["worker_b"] = "succeeded"
        except Exception as exc:  # noqa: BLE001
            with lock:
                outcomes["worker_b"] = f"error:{exc}"
        finally:
            django_db.close_old_connections()

    def worker_a_attempts_stale_completion():
        django_db.close_old_connections()
        barrier.wait()
        try:
            complete_delivery_success(delivery_id=delivery.id, claim_token=stale_token)
            with lock:
                outcomes["worker_a"] = "succeeded"
        except Exception as exc:  # noqa: BLE001
            with lock:
                outcomes["worker_a"] = type(exc).__name__
        finally:
            django_db.close_old_connections()

    _run_in_threads(worker_b_completes, worker_a_attempts_stale_completion)

    assert outcomes["worker_b"] == "succeeded"
    assert outcomes["worker_a"] == "StaleClaimError"
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED


# ---------------------------------------------------------------------------
# Race C: two reclaimers target the same expired claim simultaneously.
# ---------------------------------------------------------------------------


def test_race_two_reclaimers_same_expired_claim():
    now = timezone.now()
    delivery = DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=uuid.uuid4(),
        claimed_at=now - timedelta(minutes=10),
        lease_expires_at=now - timedelta(minutes=1),
        attempt_count=1,
    )
    DeliveryAttempt.objects.create(
        delivery=delivery,
        attempt_number=1,
        claim_token=delivery.claim_token,
        status=AttemptStatus.IN_PROGRESS,
        started_at=now - timedelta(minutes=10),
    )

    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []

    def reclaimer():
        django_db.close_old_connections()
        barrier.wait()
        try:
            results.append(reclaim_expired_delivery(delivery_id=delivery.id))
        except DeliveryNotClaimableError as exc:
            errors.append(exc)
        finally:
            django_db.close_old_connections()

    _run_in_threads(reclaimer, reclaimer)

    assert len(results) == 1, "exactly one reclaimer must win"
    assert len(errors) == 1, "exactly one reclaimer must lose safely"
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.CLAIMED
    assert delivery.attempt_count == 2
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 2


def test_workspace_ownership_survives_concurrent_access():
    """Not a race per se, but placed alongside the other real-DB tests
    (section 22): a workspace-scoped selector never crosses tenant lines
    even when the underlying row is mid-claim."""
    from notifications.selectors import get_delivery_for_workspace
    from workspaces.tests.factories import WorkspaceFactory

    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    delivery = DeliveryFactory(
        workspace=workspace_a, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    claim_delivery(delivery_id=delivery.id)

    assert (
        get_delivery_for_workspace(workspace_id=workspace_a.id, delivery_id=delivery.id) is not None
    )
    assert get_delivery_for_workspace(workspace_id=workspace_b.id, delivery_id=delivery.id) is None
