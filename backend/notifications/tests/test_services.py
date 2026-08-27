"""Delivery service-layer tests: claiming, leases, reclaim, completion, and
stale-worker protection (section 25). Clock is always injected explicitly —
no real sleeps (section 24)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from notifications.errors import DeliveryNotClaimableError, DeliveryNotFoundError, StaleClaimError
from notifications.models import (
    AttemptStatus,
    Delivery,
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
)
from notifications.services import (
    claim_delivery,
    complete_delivery_failure,
    complete_delivery_success,
    create_delivery,
    reclaim_expired_delivery,
)
from notifications.tests.factories import DeliveryFactory
from workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# create_delivery
# ---------------------------------------------------------------------------


def test_create_delivery_uses_server_default_max_attempts(settings):
    settings.DELIVERY_DEFAULT_MAX_ATTEMPTS = 7
    workspace = WorkspaceFactory()
    delivery = create_delivery(workspace=workspace, channel=DeliveryChannel.WEBHOOK)
    assert delivery.max_attempts == 7
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.next_attempt_at <= timezone.now()


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------


def test_claim_due_pending_delivery():
    delivery = DeliveryFactory(next_attempt_at=timezone.now() - timedelta(seconds=1))
    claimed, token = claim_delivery(delivery_id=delivery.id)
    assert claimed.status == DeliveryStatus.CLAIMED
    assert claimed.attempt_count == 1
    assert claimed.claim_token == token
    assert claimed.claimed_at is not None
    assert claimed.lease_expires_at is not None
    assert claimed.first_attempt_at is not None
    attempt = DeliveryAttempt.objects.get(delivery=claimed, attempt_number=1)
    assert attempt.claim_token == token
    assert attempt.status == AttemptStatus.IN_PROGRESS


def test_claim_uses_server_configured_lease_duration(settings):
    settings.DELIVERY_CLAIM_LEASE_SECONDS = 42
    now = timezone.now()
    delivery = DeliveryFactory(next_attempt_at=now)
    claimed, _ = claim_delivery(delivery_id=delivery.id, now=now)
    assert claimed.lease_expires_at == now + timedelta(seconds=42)


def test_cannot_claim_future_retry():
    delivery = DeliveryFactory(
        status=DeliveryStatus.RETRY_SCHEDULED, next_attempt_at=timezone.now() + timedelta(hours=1)
    )
    with pytest.raises(DeliveryNotClaimableError):
        claim_delivery(delivery_id=delivery.id)


def test_can_claim_due_retry_scheduled():
    delivery = DeliveryFactory(
        status=DeliveryStatus.RETRY_SCHEDULED,
        next_attempt_at=timezone.now() - timedelta(seconds=1),
        attempt_count=1,
    )
    claimed, _ = claim_delivery(delivery_id=delivery.id)
    assert claimed.status == DeliveryStatus.CLAIMED
    assert claimed.attempt_count == 2


@pytest.mark.parametrize(
    "status", [DeliveryStatus.DELIVERED, DeliveryStatus.FAILED, DeliveryStatus.DEAD]
)
def test_cannot_claim_terminal_states(status):
    delivery = DeliveryFactory(status=status, next_attempt_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(DeliveryNotClaimableError):
        claim_delivery(delivery_id=delivery.id)


def test_cannot_steal_unexpired_claim():
    now = timezone.now()
    delivery = DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=uuid.uuid4(),
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )
    with pytest.raises(DeliveryNotClaimableError):
        claim_delivery(delivery_id=delivery.id)
    with pytest.raises(DeliveryNotClaimableError):
        reclaim_expired_delivery(delivery_id=delivery.id)


def test_cannot_claim_nonexistent_delivery():
    with pytest.raises(DeliveryNotClaimableError):
        claim_delivery(delivery_id=uuid.uuid4())


def test_claim_defends_against_attempt_count_already_at_budget():
    """A delivery should never actually reach RETRY_SCHEDULED with
    ``attempt_count == max_attempts`` (``complete_delivery_failure`` would
    have terminated it instead) — this exercises the defensive guard as a
    direct unit test of that invariant, independent of how such a row could
    come to exist."""
    delivery = DeliveryFactory(
        status=DeliveryStatus.RETRY_SCHEDULED,
        next_attempt_at=timezone.now() - timedelta(seconds=1),
        max_attempts=2,
        attempt_count=2,
    )
    with pytest.raises(DeliveryNotClaimableError):
        claim_delivery(delivery_id=delivery.id)


def test_completion_on_nonexistent_delivery_raises_not_found():
    with pytest.raises(DeliveryNotFoundError):
        complete_delivery_success(delivery_id=uuid.uuid4(), claim_token=uuid.uuid4())
    with pytest.raises(DeliveryNotFoundError):
        complete_delivery_failure(
            delivery_id=uuid.uuid4(),
            claim_token=uuid.uuid4(),
            safe_error_code="irrelevant",
            retryable=True,
        )


# ---------------------------------------------------------------------------
# Reclaim
# ---------------------------------------------------------------------------


def test_expired_claim_can_be_reclaimed_with_new_token():
    now = timezone.now()
    original_token = uuid.uuid4()
    delivery = DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=original_token,
        claimed_at=now - timedelta(minutes=10),
        lease_expires_at=now - timedelta(minutes=5),
        attempt_count=1,
    )
    DeliveryAttempt.objects.create(
        delivery=delivery,
        attempt_number=1,
        claim_token=original_token,
        status=AttemptStatus.IN_PROGRESS,
        started_at=now - timedelta(minutes=10),
    )
    reclaimed, new_token = reclaim_expired_delivery(delivery_id=delivery.id, now=now)
    assert reclaimed.status == DeliveryStatus.CLAIMED
    assert new_token != original_token
    assert reclaimed.claim_token == new_token
    assert reclaimed.attempt_count == 2
    assert DeliveryAttempt.objects.filter(delivery=delivery, attempt_number=2).exists()


def test_reclaim_rejects_unexpired_claim():
    now = timezone.now()
    delivery = DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=uuid.uuid4(),
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )
    with pytest.raises(DeliveryNotClaimableError):
        reclaim_expired_delivery(delivery_id=delivery.id, now=now)


# ---------------------------------------------------------------------------
# Completion — success
# ---------------------------------------------------------------------------


def test_success_completion_marks_delivered_and_releases_claim():
    delivery = DeliveryFactory(next_attempt_at=timezone.now() - timedelta(seconds=1))
    claimed, token = claim_delivery(delivery_id=delivery.id)
    completed = complete_delivery_success(delivery_id=claimed.id, claim_token=token)
    assert completed.status == DeliveryStatus.DELIVERED
    assert completed.delivered_at is not None
    assert completed.claim_token is None
    assert completed.claimed_at is None
    assert completed.lease_expires_at is None
    attempt = DeliveryAttempt.objects.get(delivery=completed, attempt_number=1)
    assert attempt.status == AttemptStatus.SUCCEEDED
    assert attempt.completed_at is not None
    assert attempt.latency_ms is not None


# ---------------------------------------------------------------------------
# Completion — failure foundation
# ---------------------------------------------------------------------------


def test_retryable_failure_with_budget_remaining_schedules_retry():
    delivery = DeliveryFactory(
        max_attempts=3, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    claimed, token = claim_delivery(delivery_id=delivery.id)
    now = timezone.now()
    result = complete_delivery_failure(
        delivery_id=claimed.id,
        claim_token=token,
        safe_error_code="provider_timeout",
        retryable=True,
        retry_delay_seconds=30,
        now=now,
    )
    assert result.status == DeliveryStatus.RETRY_SCHEDULED
    assert result.next_attempt_at == now + timedelta(seconds=30)
    assert result.last_error_code == "provider_timeout"
    assert result.claim_token is None
    assert result.failed_at is None


def test_retryable_failure_with_budget_exhausted_terminates_as_failed():
    delivery = DeliveryFactory(
        max_attempts=1, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    claimed, token = claim_delivery(delivery_id=delivery.id)
    result = complete_delivery_failure(
        delivery_id=claimed.id,
        claim_token=token,
        safe_error_code="provider_timeout",
        retryable=True,
    )
    assert result.status == DeliveryStatus.FAILED
    assert result.failed_at is not None
    assert result.attempt_count == result.max_attempts


def test_non_retryable_failure_terminates_as_dead_even_with_budget_remaining():
    delivery = DeliveryFactory(
        max_attempts=5, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    claimed, token = claim_delivery(delivery_id=delivery.id)
    result = complete_delivery_failure(
        delivery_id=claimed.id,
        claim_token=token,
        safe_error_code="invalid_recipient",
        retryable=False,
    )
    assert result.status == DeliveryStatus.DEAD
    assert result.failed_at is not None
    attempt = DeliveryAttempt.objects.get(delivery=result, attempt_number=1)
    assert attempt.retryable is False
    assert attempt.status == AttemptStatus.FAILED


def test_dead_delivery_is_never_reopened_by_a_later_claim_attempt():
    delivery = DeliveryFactory(
        max_attempts=5, next_attempt_at=timezone.now() - timedelta(seconds=1)
    )
    claimed, token = claim_delivery(delivery_id=delivery.id)
    complete_delivery_failure(
        delivery_id=claimed.id,
        claim_token=token,
        safe_error_code="invalid_recipient",
        retryable=False,
    )
    with pytest.raises(DeliveryNotClaimableError):
        claim_delivery(delivery_id=delivery.id)


# ---------------------------------------------------------------------------
# Stale-claim protection (section 7, 15)
# ---------------------------------------------------------------------------


def test_stale_claim_success_completion_rejected():
    now = timezone.now()
    delivery = DeliveryFactory(next_attempt_at=now - timedelta(minutes=10))
    claimed, stale_token = claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)
    # Worker A's lease expires; Worker B reclaims with a new token and
    # completes successfully.
    reclaimed, fresh_token = reclaim_expired_delivery(
        delivery_id=delivery.id, now=now + timedelta(minutes=1)
    )
    complete_delivery_success(
        delivery_id=reclaimed.id, claim_token=fresh_token, now=now + timedelta(minutes=1, seconds=1)
    )
    # Worker A wakes up and tries to complete with its now-stale token.
    with pytest.raises(StaleClaimError):
        complete_delivery_success(delivery_id=delivery.id, claim_token=stale_token)
    delivered = Delivery.objects.get(pk=delivery.id)
    assert delivered.status == DeliveryStatus.DELIVERED


def test_stale_claim_failure_completion_rejected_and_never_overwrites_newer_state():
    now = timezone.now()
    delivery = DeliveryFactory(next_attempt_at=now - timedelta(minutes=10))
    _, stale_token = claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)
    reclaimed, fresh_token = reclaim_expired_delivery(
        delivery_id=delivery.id, now=now + timedelta(minutes=1)
    )
    complete_delivery_success(
        delivery_id=reclaimed.id, claim_token=fresh_token, now=now + timedelta(minutes=1, seconds=1)
    )
    with pytest.raises(StaleClaimError):
        complete_delivery_failure(
            delivery_id=delivery.id,
            claim_token=stale_token,
            safe_error_code="worker_a_thought_it_failed",
            retryable=True,
        )
    delivered = Delivery.objects.get(pk=delivery.id)
    assert delivered.status == DeliveryStatus.DELIVERED
    assert delivered.last_error_code == ""


def test_completion_with_wrong_token_on_active_claim_rejected():
    delivery = DeliveryFactory(next_attempt_at=timezone.now() - timedelta(seconds=1))
    claimed, _real_token = claim_delivery(delivery_id=delivery.id)
    with pytest.raises(StaleClaimError):
        complete_delivery_success(delivery_id=claimed.id, claim_token=uuid.uuid4())
