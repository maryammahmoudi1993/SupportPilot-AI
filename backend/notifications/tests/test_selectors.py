"""Selector tests: due-work queries, expired-lease queries, workspace
isolation, and bounded attempt history (section 16, 22)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from notifications.models import AttemptStatus, DeliveryAttempt, DeliveryStatus
from notifications.selectors import (
    attempt_history,
    due_claimable_deliveries,
    expired_claimed_deliveries,
    get_delivery_for_workspace,
)
from notifications.tests.factories import DeliveryFactory
from workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def test_due_claimable_deliveries_includes_due_pending_and_retry_scheduled():
    now = timezone.now()
    due_pending = DeliveryFactory(
        status=DeliveryStatus.PENDING, next_attempt_at=now - timedelta(seconds=1)
    )
    due_retry = DeliveryFactory(
        status=DeliveryStatus.RETRY_SCHEDULED, next_attempt_at=now - timedelta(seconds=1)
    )
    DeliveryFactory(status=DeliveryStatus.PENDING, next_attempt_at=now + timedelta(hours=1))
    DeliveryFactory(status=DeliveryStatus.DELIVERED, next_attempt_at=now - timedelta(seconds=1))

    results = set(due_claimable_deliveries(now=now).values_list("id", flat=True))
    assert results == {due_pending.id, due_retry.id}


def test_expired_claimed_deliveries_only_returns_expired_leases():
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
    results = set(expired_claimed_deliveries(now=now).values_list("id", flat=True))
    assert results == {expired.id}


def test_get_delivery_for_workspace_scopes_lookup():
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    delivery = DeliveryFactory(workspace=workspace_a)

    assert (
        get_delivery_for_workspace(workspace_id=workspace_a.id, delivery_id=delivery.id) == delivery
    )
    assert get_delivery_for_workspace(workspace_id=workspace_b.id, delivery_id=delivery.id) is None


def test_get_delivery_for_workspace_missing_id_returns_none():
    workspace = WorkspaceFactory()
    assert get_delivery_for_workspace(workspace_id=workspace.id, delivery_id=uuid.uuid4()) is None


def test_attempt_history_is_bounded_and_newest_first():
    delivery = DeliveryFactory()
    now = timezone.now()
    for number in range(1, 6):
        DeliveryAttempt.objects.create(
            delivery=delivery,
            attempt_number=number,
            claim_token=uuid.uuid4(),
            status=AttemptStatus.FAILED,
            started_at=now,
        )
    history = list(attempt_history(delivery=delivery, limit=3))
    assert [a.attempt_number for a in history] == [5, 4, 3]
