"""Real PostgreSQL concurrency (Phase 13 section 13, 38, 61) — two HTTP
deliveries of the same event, and duplicate task redelivery during
processing, proven with real threads against real row locks/constraints,
mirroring ``webhooks.tests.test_concurrency``."""

from __future__ import annotations

import threading

import django.db as django_db
import pytest

from agents import services as agent_services
from agents.models import AgentRun
from agents.providers.fake import DeterministicFakeLLMProvider, FakeLLMScenario
from channel_ingress.models import InboundChannelEvent
from channel_ingress.security import compute_payload_digest
from channel_ingress.services import ingest_channel_event, process_inbound_channel_event
from channel_ingress.tests.factories import ChannelEndpointFactory
from conversations.models import Conversation, Message, MessageSenderType

pytestmark = pytest.mark.django_db(transaction=True)


def test_two_concurrent_deliveries_of_the_same_event_create_one_row():
    endpoint = ChannelEndpointFactory()
    body = b'{"event_id":"evt-1"}'
    digest = compute_payload_digest(body)

    barrier = threading.Barrier(2)
    results: list = []
    results_lock = threading.Lock()

    def worker():
        django_db.close_old_connections()
        barrier.wait()
        try:
            event = ingest_channel_event(
                endpoint=endpoint,
                provider_event_id="evt-1",
                payload_digest=digest,
                external_identity="cust-1",
                body="hello",
            )
            with results_lock:
                results.append(event.id)
        finally:
            django_db.close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    assert results[0] == results[1]
    assert InboundChannelEvent.objects.filter(endpoint=endpoint).count() == 1


def test_two_workers_processing_the_same_event_produce_one_message_and_one_run(monkeypatch):
    provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="answer"))
    monkeypatch.setattr(agent_services, "get_llm_provider", lambda: provider)

    endpoint = ChannelEndpointFactory()
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hello",
    )

    barrier = threading.Barrier(2)
    results: list = []
    results_lock = threading.Lock()

    def worker():
        django_db.close_old_connections()
        barrier.wait()
        try:
            outcome = process_inbound_channel_event(str(event.id))
            with results_lock:
                results.append(outcome)
        finally:
            django_db.close_old_connections()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    assert Conversation.objects.filter(workspace=endpoint.workspace).count() == 1
    assert (
        Message.objects.filter(
            workspace=endpoint.workspace, sender_type=MessageSenderType.CUSTOMER
        ).count()
        == 1
    )
    assert AgentRun.objects.filter(workspace=endpoint.workspace).count() == 1


def test_duplicate_task_redelivery_after_processing_is_a_safe_no_op(monkeypatch):
    provider = DeterministicFakeLLMProvider(FakeLLMScenario(response="answer"))
    monkeypatch.setattr(agent_services, "get_llm_provider", lambda: provider)

    endpoint = ChannelEndpointFactory()
    event = ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity="cust-1",
        body="hello",
    )
    process_inbound_channel_event(str(event.id))
    process_inbound_channel_event(str(event.id))

    assert (
        Message.objects.filter(
            workspace=endpoint.workspace, sender_type=MessageSenderType.CUSTOMER
        ).count()
        == 1
    )
    assert AgentRun.objects.filter(workspace=endpoint.workspace).count() == 1
