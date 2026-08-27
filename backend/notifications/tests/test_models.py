"""Delivery/DeliveryAttempt model defaults and DB constraints (section 5, 18, 25)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from notifications.models import (
    AttemptStatus,
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
)
from notifications.tests.factories import DeliveryFactory

pytestmark = pytest.mark.django_db


def test_initial_state_and_defaults():
    delivery = DeliveryFactory()
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempt_count == 0
    assert delivery.max_attempts == 5
    assert delivery.claim_token is None
    assert delivery.claimed_at is None
    assert delivery.lease_expires_at is None
    assert delivery.first_attempt_at is None
    assert delivery.delivered_at is None
    assert delivery.failed_at is None
    assert delivery.last_error_code == ""


def test_attempt_count_cannot_go_negative():
    delivery = DeliveryFactory.build(max_attempts=3, attempt_count=-1)
    delivery.workspace = DeliveryFactory().workspace
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            delivery.save()


def test_max_attempts_must_be_positive():
    delivery = DeliveryFactory.build(max_attempts=0)
    delivery.workspace = DeliveryFactory().workspace
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            delivery.save()


def test_attempt_count_cannot_exceed_max_attempts():
    delivery = DeliveryFactory.build(max_attempts=1, attempt_count=2)
    delivery.workspace = DeliveryFactory().workspace
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            delivery.save()


def test_claim_fields_must_be_all_or_nothing_when_not_claimed():
    delivery = DeliveryFactory.build(status=DeliveryStatus.PENDING, claim_token=uuid.uuid4())
    delivery.workspace = DeliveryFactory().workspace
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            delivery.save()


def test_claim_fields_required_when_claimed():
    delivery = DeliveryFactory.build(status=DeliveryStatus.CLAIMED)
    delivery.workspace = DeliveryFactory().workspace
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            delivery.save()


def test_claimed_delivery_with_full_claim_identity_is_valid():
    now = timezone.now()
    delivery = DeliveryFactory(
        status=DeliveryStatus.CLAIMED,
        claim_token=uuid.uuid4(),
        claimed_at=now,
        lease_expires_at=now + timedelta(minutes=5),
    )
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.CLAIMED


def test_attempt_number_unique_per_delivery():
    delivery = DeliveryFactory()
    now = timezone.now()
    DeliveryAttempt.objects.create(
        delivery=delivery,
        attempt_number=1,
        claim_token=uuid.uuid4(),
        status=AttemptStatus.SUCCEEDED,
        started_at=now,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DeliveryAttempt.objects.create(
                delivery=delivery,
                attempt_number=1,
                claim_token=uuid.uuid4(),
                status=AttemptStatus.IN_PROGRESS,
                started_at=now,
            )


def test_delivery_channel_choices_include_notification_and_webhook():
    assert DeliveryChannel.NOTIFICATION == "notification"
    assert DeliveryChannel.WEBHOOK == "webhook"


def test_delivery_and_attempt_str_are_stable_and_safe():
    delivery = DeliveryFactory()
    assert str(delivery) == f"{delivery.id}:{delivery.channel}:{delivery.status}"
    attempt = DeliveryAttempt.objects.create(
        delivery=delivery,
        attempt_number=1,
        claim_token=uuid.uuid4(),
        status=AttemptStatus.IN_PROGRESS,
        started_at=timezone.now(),
    )
    assert str(attempt) == f"{delivery.id}:1:{AttemptStatus.IN_PROGRESS}"
