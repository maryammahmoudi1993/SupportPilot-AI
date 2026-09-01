"""Identity resolution and conversation/thread resolution matrix (Phase 13
section 27-30, 60)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from channel_ingress.conversation_resolution import resolve_conversation
from channel_ingress.errors import IdentityNotFoundError
from channel_ingress.identity import channel_identity_key, resolve_customer_identity
from channel_ingress.models import UnknownCustomerPolicy
from channel_ingress.schemas import CanonicalInboundMessage
from channel_ingress.tests.factories import ChannelEndpointFactory, EmailEndpointFactory
from customers.tests.factories import CustomerFactory

pytestmark = pytest.mark.django_db


def _canonical(**overrides):
    kwargs = dict(
        channel="email",
        provider="generic_email",
        provider_event_id="evt-1",
        external_identity="jane@example.com",
        body="hi",
        received_at=timezone.now(),
    )
    kwargs.update(overrides)
    return CanonicalInboundMessage(**kwargs)


def test_unknown_identity_creates_a_customer_when_policy_is_create():
    endpoint = EmailEndpointFactory(unknown_customer_policy=UnknownCustomerPolicy.CREATE)
    customer = resolve_customer_identity(
        workspace=endpoint.workspace, endpoint=endpoint, canonical=_canonical()
    )
    assert customer.external_id == channel_identity_key(
        channel=endpoint.channel, external_identity="jane@example.com"
    )
    assert customer.email == "jane@example.com"


def test_unknown_identity_is_rejected_when_policy_is_reject():
    endpoint = EmailEndpointFactory(unknown_customer_policy=UnknownCustomerPolicy.REJECT)
    with pytest.raises(IdentityNotFoundError):
        resolve_customer_identity(
            workspace=endpoint.workspace, endpoint=endpoint, canonical=_canonical()
        )


def test_known_identity_reuses_the_existing_customer():
    endpoint = EmailEndpointFactory()
    external_id = channel_identity_key(
        channel=endpoint.channel, external_identity="jane@example.com"
    )
    existing = CustomerFactory(workspace=endpoint.workspace, external_id=external_id)
    resolved = resolve_customer_identity(
        workspace=endpoint.workspace, endpoint=endpoint, canonical=_canonical()
    )
    assert resolved.id == existing.id


def test_inactive_customer_is_still_resolved_not_rejected():
    """Deactivation controls staff-facing customer management, not whether
    a real customer's channel messages keep routing to their history
    (section 27's docstring rationale)."""
    endpoint = EmailEndpointFactory()
    external_id = channel_identity_key(
        channel=endpoint.channel, external_identity="jane@example.com"
    )
    existing = CustomerFactory(
        workspace=endpoint.workspace, external_id=external_id, is_active=False
    )
    resolved = resolve_customer_identity(
        workspace=endpoint.workspace, endpoint=endpoint, canonical=_canonical()
    )
    assert resolved.id == existing.id


def test_same_email_in_two_workspaces_resolves_to_two_distinct_customers():
    endpoint_a = EmailEndpointFactory()
    endpoint_b = EmailEndpointFactory()
    customer_a = resolve_customer_identity(
        workspace=endpoint_a.workspace, endpoint=endpoint_a, canonical=_canonical()
    )
    customer_b = resolve_customer_identity(
        workspace=endpoint_b.workspace, endpoint=endpoint_b, canonical=_canonical()
    )
    assert customer_a.id != customer_b.id
    assert customer_a.workspace_id != customer_b.workspace_id


def test_same_raw_identity_on_two_channels_does_not_collide_on_one_customer():
    """Section 29: an email adapter and a generic-webhook adapter both
    resolving the literal string ``jane@example.com`` must never merge onto
    the same customer record."""
    email_endpoint = EmailEndpointFactory()
    generic_endpoint = ChannelEndpointFactory(workspace=email_endpoint.workspace)
    email_customer = resolve_customer_identity(
        workspace=email_endpoint.workspace,
        endpoint=email_endpoint,
        canonical=_canonical(external_identity="jane@example.com"),
    )
    generic_customer = resolve_customer_identity(
        workspace=generic_endpoint.workspace,
        endpoint=generic_endpoint,
        canonical=_canonical(channel="generic_webhook", external_identity="jane@example.com"),
    )
    assert email_customer.id != generic_customer.id


def test_new_thread_creates_a_new_conversation():
    endpoint = EmailEndpointFactory()
    customer = CustomerFactory(workspace=endpoint.workspace)
    conversation = resolve_conversation(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        customer=customer,
        canonical=_canonical(provider_thread_id="thread-1"),
    )
    assert conversation.metadata["channel_endpoint_id"] == str(endpoint.id)


def test_reply_to_existing_thread_reuses_the_conversation():
    endpoint = EmailEndpointFactory()
    customer = CustomerFactory(workspace=endpoint.workspace)
    first = resolve_conversation(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        customer=customer,
        canonical=_canonical(provider_thread_id="thread-1"),
    )
    second = resolve_conversation(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        customer=customer,
        canonical=_canonical(provider_thread_id="thread-1", subject="Re: hi"),
    )
    assert first.id == second.id


def test_same_provider_thread_id_on_two_endpoints_does_not_merge_conversations():
    endpoint_a = EmailEndpointFactory()
    endpoint_b = EmailEndpointFactory(workspace=endpoint_a.workspace)
    customer = CustomerFactory(workspace=endpoint_a.workspace)
    conv_a = resolve_conversation(
        workspace=endpoint_a.workspace,
        endpoint=endpoint_a,
        customer=customer,
        canonical=_canonical(provider_thread_id="shared-thread-id"),
    )
    conv_b = resolve_conversation(
        workspace=endpoint_b.workspace,
        endpoint=endpoint_b,
        customer=customer,
        canonical=_canonical(provider_thread_id="shared-thread-id"),
    )
    assert conv_a.id != conv_b.id


def test_same_sender_different_threads_does_not_merge_conversations():
    """Identity and threading are separate problems (section 24): the same
    sender emailing about two unrelated things must not be forced into one
    conversation just because the sender matches."""
    endpoint = EmailEndpointFactory()
    customer = CustomerFactory(workspace=endpoint.workspace)
    conv_a = resolve_conversation(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        customer=customer,
        canonical=_canonical(provider_thread_id="thread-a"),
    )
    conv_b = resolve_conversation(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        customer=customer,
        canonical=_canonical(provider_thread_id="thread-b"),
    )
    assert conv_a.id != conv_b.id
