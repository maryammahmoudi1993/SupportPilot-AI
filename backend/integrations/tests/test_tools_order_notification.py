"""``order.lookup`` / ``shipment.lookup`` / ``notification.send`` tool tests
(section 30-32, 57-60, 97, 100).

Phase 10 Block 2: ``notification.send`` no longer performs synchronous
provider I/O — it durably enqueues a ``Delivery``/``NotificationDelivery``
and returns ``queued``. These tests exercise the tool call and the async
worker (``process_delivery_task``) as two explicit steps, exactly as
production does (a Celery worker processes the delivery later, not inside
the request that queued it)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from customers.tests.factories import CustomerFactory
from integrations.errors import IntegrationTimeoutError
from integrations.models import IntegrationProvider
from integrations.providers.fakes import FakeNotificationProvider
from notifications.models import Delivery, DeliveryStatus, NotificationDelivery
from notifications.tasks import process_delivery_task
from tools.errors import ToolError
from tools.execution import execute_tool

from .factories import IntegrationConnectionFactory, allow_all_policy, bind_tool, running_run


@pytest.mark.django_db(transaction=True)
class TestOrderShipmentLookup:
    def _setup(self, *, orders=None, shipments=None):
        run = running_run()
        bind_tool(run, "order.lookup")
        bind_tool(run, "shipment.lookup")
        IntegrationConnectionFactory(
            workspace=run.workspace,
            provider=IntegrationProvider.DEMO_COMMERCE,
            configuration={"orders": orders or {}, "shipments": shipments or {}},
        )
        return run

    def test_order_found(self):
        run = self._setup(
            orders={
                "ORD-1": {
                    "status": "processing",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "amount_minor": 2500,
                    "currency": "usd",
                    "tracking_reference": "TRK-1",
                }
            }
        )
        result = execute_tool(
            agent_run=run, tool_key="order.lookup", arguments={"order_reference": "ORD-1"}
        )
        assert result.output["status"] == "processing"
        assert result.output["amount_minor"] == 2500
        assert result.output["currency"] == "USD"

    def test_order_not_found(self):
        run = self._setup()
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run, tool_key="order.lookup", arguments={"order_reference": "missing"}
            )
        assert exc_info.value.code == "order_not_found"

    def test_incomplete_catalog_entry_is_a_malformed_response_not_a_crash(self):
        run = self._setup(orders={"ORD-1": {"status": "processing"}})
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run, tool_key="order.lookup", arguments={"order_reference": "ORD-1"}
            )
        assert exc_info.value.code == "integration_malformed_response"

    def test_shipment_found(self):
        run = self._setup(
            shipments={
                "TRK-1": {
                    "order_id": "ORD-1",
                    "status": "in_transit",
                    "carrier": "ups",
                }
            }
        )
        result = execute_tool(
            agent_run=run, tool_key="shipment.lookup", arguments={"shipment_reference": "TRK-1"}
        )
        assert result.output["status"] == "in_transit"
        assert result.output["carrier"] == "ups"

    def test_shipment_not_found(self):
        run = self._setup()
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="shipment.lookup",
                arguments={"shipment_reference": "missing"},
            )
        assert exc_info.value.code == "shipment_not_found"

    def test_no_demo_commerce_connection_is_not_configured(self):
        run = running_run()
        bind_tool(run, "order.lookup")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(agent_run=run, tool_key="order.lookup", arguments={"order_reference": "x"})
        assert exc_info.value.code == "integration_not_configured"


@pytest.mark.django_db(transaction=True)
class TestNotificationSend:
    def _setup(self, monkeypatch, *, fake=None):
        fake = fake or FakeNotificationProvider()
        run = running_run()
        bind_tool(run, "notification.send")
        allow_all_policy(run.workspace)  # this suite tests provider mechanics, not Phase 8 gating
        IntegrationConnectionFactory(workspace=run.workspace, provider=IntegrationProvider.EMAIL)
        monkeypatch.setattr(
            "integrations.services.get_notification_provider", lambda provider: fake
        )
        return run, fake

    def test_success_queues_delivery_then_worker_delivers(self, monkeypatch):
        run, fake = self._setup(monkeypatch)
        customer = CustomerFactory(workspace=run.workspace, email="customer@example.com")
        result = execute_tool(
            agent_run=run,
            tool_key="notification.send",
            arguments={
                "customer_id": str(customer.id),
                "subject": "Your order shipped",
                "body": "It is on the way.",
            },
        )
        # The tool call itself never touches the provider (section 8) — it
        # only accepts the request and durably enqueues it.
        assert result.output["status"] == "queued"
        delivery_id = result.output["delivery_id"]
        assert fake.outbox == []
        delivery = Delivery.objects.get(pk=delivery_id)
        assert delivery.status == DeliveryStatus.PENDING
        notification_delivery = NotificationDelivery.objects.get(delivery_id=delivery_id)
        assert notification_delivery.source_tool_execution_id == result.execution.id

        worker_result = process_delivery_task.apply(args=[delivery_id]).get()
        assert worker_result == "processed"
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED
        assert fake.outbox == [
            {
                "to": "customer@example.com",
                "subject": "Your order shipped",
                "body": "It is on the way.",
            }
        ]

    def test_recipient_cannot_be_supplied_directly(self, monkeypatch):
        """The tool's input schema has no recipient/email field at all — an
        attempt to smuggle one in is rejected by strict schema validation
        (section 58)."""
        run, fake = self._setup(monkeypatch)
        customer = CustomerFactory(workspace=run.workspace, email="customer@example.com")
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="notification.send",
                arguments={
                    "customer_id": str(customer.id),
                    "subject": "x",
                    "body": "y",
                    "recipient_email": "attacker@evil.com",
                },
            )
        assert exc_info.value.code == "tool_invalid_input"
        assert fake.outbox == []

    def test_customer_without_email_is_rejected(self, monkeypatch):
        run, fake = self._setup(monkeypatch)
        customer = CustomerFactory(workspace=run.workspace, email=None)
        with pytest.raises(ToolError) as exc_info:
            execute_tool(
                agent_run=run,
                tool_key="notification.send",
                arguments={"customer_id": str(customer.id), "subject": "x", "body": "y"},
            )
        assert exc_info.value.code == "integration_invalid_request"

    def test_repeated_call_same_idempotency_key_reuses_one_logical_delivery(self, monkeypatch):
        run, fake = self._setup(monkeypatch)
        customer = CustomerFactory(workspace=run.workspace, email="customer@example.com")
        arguments = {"customer_id": str(customer.id), "subject": "x", "body": "y"}
        first = execute_tool(
            agent_run=run, tool_key="notification.send", arguments=arguments, idempotency_key="k1"
        )
        second = execute_tool(
            agent_run=run, tool_key="notification.send", arguments=arguments, idempotency_key="k1"
        )
        # Same ToolExecution replay -> same logical NotificationDelivery
        # (section 11), never a second one.
        assert first.output["delivery_id"] == second.output["delivery_id"]
        assert NotificationDelivery.objects.count() == 1

        process_delivery_task.apply(args=[first.output["delivery_id"]]).get()
        assert len(fake.outbox) == 1

    def test_ambiguous_timeout_retry_does_not_double_send(self, monkeypatch):
        """A provider that commits a send before raising a timeout back to
        the caller (section 22) produces an ambiguous outcome at the
        worker level — the durable retry must reuse the same stable
        idempotency key so the deterministic fake (standing in for any
        provider capable of server-side dedup) never delivers twice."""
        fake = FakeNotificationProvider(send_errors=[(IntegrationTimeoutError(), True)])
        run, fake = self._setup(monkeypatch, fake=fake)
        customer = CustomerFactory(workspace=run.workspace, email="customer@example.com")
        arguments = {"customer_id": str(customer.id), "subject": "x", "body": "y"}
        result = execute_tool(
            agent_run=run, tool_key="notification.send", arguments=arguments, idempotency_key="k1"
        )
        delivery_id = result.output["delivery_id"]

        first_outcome = process_delivery_task.apply(args=[delivery_id]).get()
        assert first_outcome == "processed"
        assert len(fake.outbox) == 1  # provider committed it despite the timeout
        delivery = Delivery.objects.get(pk=delivery_id)
        assert delivery.status == DeliveryStatus.RETRY_SCHEDULED

        Delivery.objects.filter(pk=delivery_id).update(next_attempt_at=timezone.now())
        second_outcome = process_delivery_task.apply(args=[delivery_id]).get()
        assert second_outcome == "processed"
        assert len(fake.outbox) == 1  # retry did not send a second message
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED
