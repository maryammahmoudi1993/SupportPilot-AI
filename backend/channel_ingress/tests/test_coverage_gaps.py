"""Targeted coverage for error/edge paths not already exercised by the
scenario-level test files: response-delivery failure handling, generic
adapter secret misconfiguration, service-layer exception boundaries, the
Celery task wrappers, staff detail/update views, and small webchat edges."""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from agents.tests.factories import PublishedAgentVersionFactory
from channel_ingress.adapters.generic_webhook import GenericSignedWebhookAdapter
from channel_ingress.errors import EndpointDisabledError, PayloadInvalidError, UnsupportedEventError
from channel_ingress.models import ChannelResponseDelivery, InboundChannelEventStatus
from channel_ingress.response_delivery import (
    MISSING_SNAPSHOT_ERROR_CODE,
    UNEXPECTED_ERROR_CODE,
    handle_channel_response_delivery_attempt,
    route_channel_response,
)
from channel_ingress.services import ingest_channel_event, process_inbound_channel_event
from channel_ingress.tests.factories import ChannelEndpointFactory, EmailEndpointFactory
from channel_ingress.webchat import (
    bootstrap_chat_session,
    get_session_for_token,
    list_chat_messages,
    submit_chat_message,
)
from conversations.tests.factories import MessageFactory
from customers.tests.factories import CustomerFactory
from integrations.models import IntegrationProvider
from integrations.tests.factories import IntegrationConnectionFactory
from notifications.models import DeliveryChannel, DeliveryStatus
from notifications.services import claim_delivery, create_delivery
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

pytestmark = pytest.mark.django_db


def _base(workspace) -> str:
    return f"/api/v1/workspaces/{workspace.id}/channels"


def _client(user=None) -> APIClient:
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


# --- generic adapter: signing secret misconfiguration -----------------------


def test_adapter_rejects_an_endpoint_with_no_secret_configured():
    endpoint = ChannelEndpointFactory(encrypted_signing_secret="")
    adapter = GenericSignedWebhookAdapter()
    with pytest.raises(UnsupportedEventError):
        adapter.verify_signature(endpoint=endpoint, raw_body=b"{}", headers={})


def test_adapter_rejects_an_endpoint_with_corrupt_secret_ciphertext():
    endpoint = ChannelEndpointFactory(encrypted_signing_secret="not-a-real-fernet-token")
    adapter = GenericSignedWebhookAdapter()
    with pytest.raises(UnsupportedEventError):
        adapter.verify_signature(endpoint=endpoint, raw_body=b"{}", headers={})


def test_normalize_rejects_a_non_string_body_field():
    endpoint = ChannelEndpointFactory()
    adapter = GenericSignedWebhookAdapter()
    with pytest.raises(PayloadInvalidError):
        adapter.normalize(
            endpoint=endpoint,
            parsed={"event_id": "e", "external_id": "c", "body": 12345},
        )


# --- response delivery error paths ------------------------------------------


def test_route_channel_response_with_no_conversation_returns_none():
    from agents.tests.factories import AgentRunFactory

    run = AgentRunFactory()  # no conversation, no output_message
    assert route_channel_response(run=run) is None


def test_route_channel_response_for_a_non_channel_conversation_returns_none():
    from agents.tests.factories import AgentRunFactory
    from conversations.tests.factories import ConversationFactory

    conversation = ConversationFactory()  # metadata has no channel_endpoint_id
    message = MessageFactory(conversation=conversation)
    run = AgentRunFactory(
        workspace=conversation.workspace, conversation=conversation, output_message=message
    )
    assert route_channel_response(run=run) is None


def test_handle_response_delivery_attempt_with_no_snapshot_fails_terminally():
    delivery = create_delivery(
        workspace=EmailEndpointFactory().workspace, channel=DeliveryChannel.CHANNEL_RESPONSE
    )
    _, claim_token = claim_delivery(delivery_id=delivery.id)
    handle_channel_response_delivery_attempt(delivery=delivery, claim_token=claim_token)
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == MISSING_SNAPSHOT_ERROR_CODE


def test_handle_response_delivery_attempt_unexpected_exception_fails_terminally(monkeypatch):
    connection = IntegrationConnectionFactory(provider=IntegrationProvider.EMAIL)
    endpoint = EmailEndpointFactory(
        workspace=connection.workspace, integration_connection=connection
    )
    customer = CustomerFactory(workspace=endpoint.workspace, email="jane@example.com")
    from conversations.tests.factories import ConversationFactory

    conversation = ConversationFactory(
        workspace=endpoint.workspace,
        customer=customer,
        metadata={"channel_endpoint_id": str(endpoint.id)},
    )
    message = MessageFactory(conversation=conversation)
    delivery = create_delivery(
        workspace=endpoint.workspace, channel=DeliveryChannel.CHANNEL_RESPONSE
    )
    ChannelResponseDelivery.objects.create(
        delivery=delivery,
        source_message=message,
        endpoint=endpoint,
        destination_address="jane@example.com",
        subject="hi",
        body="hi",
        idempotency_key=f"channel_response:{message.id}",
    )

    def _boom(**kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr("channel_ingress.response_delivery.send_notification", _boom)
    _, claim_token = claim_delivery(delivery_id=delivery.id)
    handle_channel_response_delivery_attempt(delivery=delivery, claim_token=claim_token)
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == UNEXPECTED_ERROR_CODE


# --- process_inbound_channel_event failure/skip paths -----------------------


def test_process_inbound_channel_event_on_an_already_processed_event_is_a_no_op():
    endpoint = ChannelEndpointFactory()
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hi",
    )
    from channel_ingress.services import mark_event_processed

    mark_event_processed(event=event, conversation=None, message=None)
    outcome = process_inbound_channel_event(str(event.id))
    assert outcome == InboundChannelEventStatus.PROCESSED


def test_process_inbound_channel_event_records_a_generic_failure(monkeypatch):
    endpoint = ChannelEndpointFactory()
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hi",
    )

    def _boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("channel_ingress.services.resolve_customer_identity", _boom)
    outcome = process_inbound_channel_event(str(event.id))
    assert outcome == InboundChannelEventStatus.FAILED
    event.refresh_from_db()
    assert event.status == InboundChannelEventStatus.FAILED
    assert event.failure_code == "processing_failed"


# --- Celery task wrappers ----------------------------------------------------


def test_tasks_delegate_to_services(monkeypatch):
    from channel_ingress import tasks

    called = {}

    def _fake_process(event_id):
        called["processed"] = event_id
        return "processed"

    monkeypatch.setattr("channel_ingress.services.process_inbound_channel_event", _fake_process)
    result = tasks.process_inbound_channel_event_task.run("evt-1")
    assert result == "processed"
    assert called["processed"] == "evt-1"

    monkeypatch.setattr("channel_ingress.recovery.recover_stuck_inbound_events", lambda: 3)
    assert tasks.recover_stuck_inbound_events_task.run() == 3


# --- staff detail/update views ----------------------------------------------


def test_endpoint_detail_view_update_changes_name_and_agent_version():
    endpoint = EmailEndpointFactory()
    membership = WorkspaceMembershipFactory(workspace=endpoint.workspace, role=WorkspaceRole.OWNER)
    new_version = PublishedAgentVersionFactory(agent_definition__workspace=endpoint.workspace)
    response = _client(membership.user).patch(
        f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/",
        {"name": "Renamed", "agent_version_id": str(new_version.id)},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["name"] == "Renamed"


def test_endpoint_detail_view_update_rejects_foreign_agent_version():
    endpoint = EmailEndpointFactory()
    membership = WorkspaceMembershipFactory(workspace=endpoint.workspace, role=WorkspaceRole.OWNER)
    response = _client(membership.user).patch(
        f"{_base(endpoint.workspace)}/endpoints/{endpoint.id}/",
        {"agent_version_id": str(uuid.uuid4())},
        format="json",
    )
    assert response.status_code == 404


def test_inbound_event_list_and_detail_views():
    endpoint = ChannelEndpointFactory()
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hi",
    )
    membership = WorkspaceMembershipFactory(workspace=endpoint.workspace, role=WorkspaceRole.VIEWER)
    listing = _client(membership.user).get(f"{_base(endpoint.workspace)}/events/")
    assert listing.status_code == 200
    assert listing.data["results"][0]["id"] == str(event.id)

    detail = _client(membership.user).get(f"{_base(endpoint.workspace)}/events/{event.id}/")
    assert detail.status_code == 200
    assert detail.data["status"] == InboundChannelEventStatus.RECEIVED

    missing = _client(membership.user).get(f"{_base(endpoint.workspace)}/events/{uuid.uuid4()}/")
    assert missing.status_code == 404


# --- small webchat edges -----------------------------------------------------


def test_get_session_for_empty_token_is_none():
    assert get_session_for_token(token="") is None


def test_submit_message_on_a_disabled_endpoint_is_rejected():
    endpoint = EmailEndpointFactory()  # not web chat, but enabled() check applies uniformly
    from channel_ingress.models import ChannelEndpointStatus
    from channel_ingress.tests.factories import ChatSessionFactory

    endpoint.status = ChannelEndpointStatus.DISABLED
    endpoint.save(update_fields=["status"])
    session = ChatSessionFactory(workspace=endpoint.workspace, endpoint=endpoint)
    with pytest.raises(EndpointDisabledError):
        submit_chat_message(session=session, client_message_id="m1", body="hi")


def test_list_messages_after_cursor_only_returns_newer_messages():
    from channel_ingress.tests.factories import WebChatEndpointFactory

    endpoint = WebChatEndpointFactory()
    session, _ = bootstrap_chat_session(endpoint=endpoint)
    from conversations.tests.factories import ConversationFactory

    conversation = ConversationFactory(workspace=endpoint.workspace)
    session.conversation = conversation
    session.save(update_fields=["conversation"])
    first = MessageFactory(conversation=conversation, body="first")
    second = MessageFactory(conversation=conversation, body="second")

    all_messages = list_chat_messages(session=session)
    assert [m.id for m in all_messages] == [first.id, second.id]

    after_first = list_chat_messages(session=session, after=str(first.id))
    assert [m.id for m in after_first] == [second.id]


# --- remaining service-layer branches ---------------------------------------


def test_agent_error_from_an_unpublished_agent_version_fails_the_event():
    from agents.models import AgentVersionStatus

    endpoint = ChannelEndpointFactory()
    endpoint.agent_version.status = AgentVersionStatus.DRAFT
    endpoint.agent_version.save(update_fields=["status"])
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hi",
    )
    outcome = process_inbound_channel_event(str(event.id))
    assert outcome == InboundChannelEventStatus.FAILED
    event.refresh_from_db()
    assert event.failure_code == "orchestration_failed"


def test_a_concurrent_conversation_race_recovers_the_winners_row():
    endpoint = ChannelEndpointFactory()
    customer = CustomerFactory(workspace=endpoint.workspace)
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hi",
        provider_thread_id="thread-1",
    )
    from django.db import IntegrityError

    from channel_ingress.conversation_resolution import thread_external_id
    from conversations.tests.factories import ConversationFactory

    winner = ConversationFactory(
        workspace=endpoint.workspace,
        customer=customer,
        external_id=thread_external_id(endpoint=endpoint, provider_thread_id="thread-1"),
    )

    def _raise_integrity_error(**kwargs):
        raise IntegrityError("duplicate key")

    import channel_ingress.services as services_module

    original = services_module.resolve_conversation
    services_module.resolve_conversation = _raise_integrity_error
    try:
        recovered = services_module._resolve_conversation_with_retry(
            workspace=endpoint.workspace,
            endpoint=endpoint,
            customer=customer,
            canonical=services_module._canonical_from_event(event),
        )
    finally:
        services_module.resolve_conversation = original
    assert recovered.id == winner.id


def test_ingress_created_metrics_failure_is_fail_open(
    monkeypatch, django_capture_on_commit_callbacks
):
    def _boom(**kwargs):
        raise RuntimeError("metrics down")

    monkeypatch.setattr("observability.metrics.observe_channel_ingress_received", _boom)
    endpoint = ChannelEndpointFactory()
    with django_capture_on_commit_callbacks(execute=True):
        event = ingest_channel_event(
            endpoint=endpoint,
            provider_event_id="evt-1",
            payload_digest="digest-a",
            external_identity="cust-1",
            body="hi",
        )
    assert event is not None  # never raised despite the metrics failure


def test_ingress_duplicate_metrics_failure_is_fail_open(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("metrics down")

    monkeypatch.setattr("observability.metrics.observe_channel_ingress_duplicate", _boom)
    endpoint = ChannelEndpointFactory()
    ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hi",
    )
    # never raised despite the metrics failure on the duplicate path
    ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hi",
    )


def test_ingress_terminal_metrics_failure_is_fail_open(monkeypatch):
    from agents import services as agent_services
    from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario

    provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="answer"))
    monkeypatch.setattr(agent_services, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(
        "observability.metrics.observe_channel_ingress_terminal",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("metrics down")),
    )
    endpoint = ChannelEndpointFactory()
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hi",
    )
    outcome = process_inbound_channel_event(str(event.id))
    assert outcome == InboundChannelEventStatus.PROCESSED
