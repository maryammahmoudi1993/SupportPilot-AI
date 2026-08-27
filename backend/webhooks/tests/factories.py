"""Webhook-domain test factories and shared helpers."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from integrations.crypto import encrypt_credentials
from webhooks.models import WebhookEndpoint, WebhookEndpointStatus, WebhookEvent, WebhookEventType
from workspaces.tests.factories import WorkspaceFactory

TEST_SECRET = "test-signing-secret-not-a-real-value"


class WebhookEndpointFactory(DjangoModelFactory):
    class Meta:
        model = WebhookEndpoint

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Endpoint {n}")
    url = "https://example.com/hook"
    status = WebhookEndpointStatus.ACTIVE
    subscribed_event_types = [WebhookEventType.APPROVAL_REQUESTED]

    @factory.lazy_attribute
    def encrypted_signing_secret(self):
        return encrypt_credentials({"secret": TEST_SECRET})


class WebhookEventFactory(DjangoModelFactory):
    class Meta:
        model = WebhookEvent

    workspace = factory.SubFactory(WorkspaceFactory)
    event_type = WebhookEventType.APPROVAL_REQUESTED
    version = 1
    payload_snapshot = factory.LazyFunction(lambda: {"summary": "test"})
