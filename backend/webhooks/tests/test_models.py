"""Webhook model defaults and DB constraints (section 4-10)."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from notifications.models import DeliveryChannel
from notifications.services import create_delivery
from webhooks.models import WebhookDelivery, WebhookEndpointStatus, WebhookEventType
from webhooks.tests.factories import WebhookEndpointFactory, WebhookEventFactory
from workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def test_endpoint_defaults():
    endpoint = WebhookEndpointFactory()
    assert endpoint.status == WebhookEndpointStatus.ACTIVE
    assert endpoint.secret_configured is True
    assert endpoint.subscribed_event_types == [WebhookEventType.APPROVAL_REQUESTED]


def test_endpoint_name_cannot_be_blank():
    endpoint = WebhookEndpointFactory.build(name="", workspace=WorkspaceFactory())
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            endpoint.save()


def test_endpoint_url_cannot_be_blank():
    endpoint = WebhookEndpointFactory.build(url="", workspace=WorkspaceFactory())
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            endpoint.save()


def test_event_version_must_be_positive():
    event = WebhookEventFactory.build(version=0, workspace=WorkspaceFactory())
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            event.save()


def test_model_str_methods_are_stable():
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    webhook_delivery = WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    assert str(endpoint) == f"{endpoint.id}:{endpoint.name}:{endpoint.status}"
    assert str(event) == f"{event.id}:{event.event_type}:v{event.version}"
    assert str(webhook_delivery) == f"{delivery.id}:{endpoint.id}:{event.id}"


def test_webhook_delivery_unique_per_endpoint_event_pair():
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery_a = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    WebhookDelivery.objects.create(
        delivery=delivery_a, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    delivery_b = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WebhookDelivery.objects.create(
                delivery=delivery_b, workspace=endpoint.workspace, endpoint=endpoint, event=event
            )
