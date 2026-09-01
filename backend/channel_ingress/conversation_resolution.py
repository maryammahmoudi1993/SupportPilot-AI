"""Conversation resolution (Phase 13 section 30).

The one service responsible for finding-or-creating the ``Conversation`` a
canonical inbound message belongs to. Never duplicates
``conversations.services``' own business rules (status transitions,
reopening) — this module only ever resolves *which* conversation, then
delegates every subsequent lifecycle concern to that service layer.
"""

from __future__ import annotations

from conversations.models import Conversation, ConversationChannel
from conversations.services import create_conversation
from customers.models import Customer
from workspaces.models import Workspace

from .models import ChannelEndpoint, ChannelType
from .schemas import CanonicalInboundMessage

#: Maps this app's channel taxonomy onto the pre-existing, broader
#: ``ConversationChannel`` enum (section 30) — never a parallel/competing
#: enum on ``Conversation`` itself.
_CONVERSATION_CHANNEL_BY_TYPE: dict[str, str] = {
    str(ChannelType.WEB_CHAT): str(ConversationChannel.CHAT),
    str(ChannelType.EMAIL): str(ConversationChannel.EMAIL),
    str(ChannelType.GENERIC_WEBHOOK): str(ConversationChannel.API),
}


def thread_external_id(*, endpoint: ChannelEndpoint, provider_thread_id: str) -> str:
    """Section 29: namespaced by ``endpoint`` so an identical raw provider
    thread id from two different channel endpoints (even in the same
    workspace) can never collide on ``Conversation.external_id``'s
    workspace-unique constraint."""
    return f"{endpoint.id}:{provider_thread_id}"[:255]


def resolve_conversation(
    *,
    workspace: Workspace,
    endpoint: ChannelEndpoint,
    customer: Customer,
    canonical: CanonicalInboundMessage,
) -> Conversation:
    """Find the existing channel conversation for this thread, or start a
    new one. Reopening a closed conversation on a new inbound message is
    handled automatically by ``conversations.services.create_inbound_message``
    (its ``_create_message`` reopen branch) — never manipulated here."""
    conversation_channel = _CONVERSATION_CHANNEL_BY_TYPE[endpoint.channel]
    external_id = (
        thread_external_id(endpoint=endpoint, provider_thread_id=canonical.provider_thread_id)
        if canonical.provider_thread_id
        else None
    )

    if external_id is not None:
        existing = Conversation.objects.filter(workspace=workspace, external_id=external_id).first()
        if existing is not None:
            return existing

    return create_conversation(
        workspace=workspace,
        customer=customer,
        channel=conversation_channel,
        subject=canonical.subject,
        external_id=external_id,
        # Section 39: the routing boundary a completed run's response uses
        # to find its way back to the originating channel endpoint, without
        # widening ``Conversation``'s own schema for a single-purpose FK.
        metadata={"channel_endpoint_id": str(endpoint.id)},
    )
