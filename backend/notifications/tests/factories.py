"""Test factories for the delivery domain."""

from __future__ import annotations

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from workspaces.tests.factories import WorkspaceFactory

from ..models import Delivery, DeliveryChannel, DeliveryStatus


class DeliveryFactory(DjangoModelFactory):
    class Meta:
        model = Delivery

    workspace = factory.SubFactory(WorkspaceFactory)
    channel = DeliveryChannel.NOTIFICATION
    status = DeliveryStatus.PENDING
    max_attempts = 5
    next_attempt_at = factory.LazyFunction(timezone.now)
