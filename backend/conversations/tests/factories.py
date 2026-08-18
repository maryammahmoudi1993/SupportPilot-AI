"""Test factories for conversations and messages."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from conversations.models import Conversation, Message, MessageDirection, MessageSenderType
from customers.tests.factories import CustomerFactory
from workspaces.tests.factories import WorkspaceFactory


class ConversationFactory(DjangoModelFactory):
    class Meta:
        model = Conversation

    workspace = factory.SubFactory(WorkspaceFactory)
    customer = factory.SubFactory(CustomerFactory, workspace=factory.SelfAttribute("..workspace"))
    subject = factory.Sequence(lambda n: f"Conversation {n}")


class MessageFactory(DjangoModelFactory):
    class Meta:
        model = Message

    conversation = factory.SubFactory(ConversationFactory)
    workspace = factory.SelfAttribute("conversation.workspace")
    sender_type = MessageSenderType.CUSTOMER
    direction = MessageDirection.INBOUND
    body = "Hello, I need help."
