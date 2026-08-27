"""Celery boundary tests (section 19-20, 25): the task calls the service and
carries no domain logic; a duplicate task delivery never creates a second
simultaneously active attempt."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from notifications.models import DeliveryAttempt, DeliveryStatus
from notifications.services import NO_HANDLER_ERROR_CODE
from notifications.tasks import process_delivery_task
from notifications.tests.factories import DeliveryFactory

pytestmark = pytest.mark.django_db


def test_task_calls_service_and_dead_letters_with_no_handler_registered():
    delivery = DeliveryFactory(next_attempt_at=timezone.now() - timedelta(seconds=1))
    result = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert result == "dead_lettered"
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == NO_HANDLER_ERROR_CODE
    assert DeliveryAttempt.objects.filter(delivery=delivery, attempt_number=1).count() == 1


def test_duplicate_task_delivery_is_a_safe_no_op():
    delivery = DeliveryFactory(next_attempt_at=timezone.now() - timedelta(seconds=1))
    first = process_delivery_task.apply(args=[str(delivery.id)]).get()
    second = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert first == "dead_lettered"
    assert second == "skipped"
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1


def test_task_on_unclaimable_delivery_skips_safely():
    delivery = DeliveryFactory(status=DeliveryStatus.DELIVERED)
    result = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert result == "skipped"
