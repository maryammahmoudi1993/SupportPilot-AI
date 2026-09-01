"""Test factories for channel_ingress."""

from __future__ import annotations

from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from agents.tests.factories import PublishedAgentVersionFactory
from channel_ingress.models import (
    ChannelEndpoint,
    ChannelType,
    ChatSession,
    InboundChannelEvent,
    hash_session_token,
)
from integrations.crypto import encrypt_credentials
from workspaces.tests.factories import WorkspaceFactory

TEST_SIGNING_SECRET = "test-signing-secret-0123456789"


class ChannelEndpointFactory(DjangoModelFactory):
    class Meta:
        model = ChannelEndpoint

    workspace = factory.SubFactory(WorkspaceFactory)
    channel = ChannelType.GENERIC_WEBHOOK
    name = factory.Sequence(lambda n: f"Channel endpoint {n}")
    agent_version = factory.SubFactory(
        PublishedAgentVersionFactory,
        agent_definition__workspace=factory.SelfAttribute("...workspace"),
    )

    @factory.lazy_attribute
    def encrypted_signing_secret(self):
        if self.channel == ChannelType.WEB_CHAT:
            return ""
        return encrypt_credentials({"secret": TEST_SIGNING_SECRET})


class WebChatEndpointFactory(ChannelEndpointFactory):
    channel = ChannelType.WEB_CHAT
    encrypted_signing_secret = ""


class EmailEndpointFactory(ChannelEndpointFactory):
    channel = ChannelType.EMAIL


class InboundChannelEventFactory(DjangoModelFactory):
    class Meta:
        model = InboundChannelEvent

    endpoint = factory.SubFactory(ChannelEndpointFactory)
    workspace = factory.SelfAttribute("endpoint.workspace")
    provider_event_id = factory.Sequence(lambda n: f"event-{n}")
    payload_digest = factory.Sequence(lambda n: f"digest-{n}")
    external_identity = "customer@example.com"
    body = "Hello, I need help."


class ChatSessionFactory(DjangoModelFactory):
    class Meta:
        model = ChatSession

    workspace = factory.SubFactory(WorkspaceFactory)
    endpoint = factory.SubFactory(
        WebChatEndpointFactory, workspace=factory.SelfAttribute("..workspace")
    )
    token_hash = factory.LazyFunction(lambda: hash_session_token("unused-default-token"))
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(hours=1))
