"""Direct contract tests for the deterministic fakes themselves (section
25, 110) — the pieces not already exercised indirectly through a tool
handler."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from integrations.errors import OrderNotFoundError, PaymentNotFoundError, ShipmentNotFoundError
from integrations.providers.base import NormalizedOrder, NormalizedShipment
from integrations.providers.fakes import (
    FakeCalendarProvider,
    FakeNotificationProvider,
    FakeOrderProvider,
    FakePaymentProvider,
    make_slot,
)


class TestFakePaymentProviderRefundOfUnknownPayment:
    def test_refund_of_a_payment_never_looked_up_is_not_found(self):
        fake = FakePaymentProvider()
        with pytest.raises(PaymentNotFoundError):
            fake.refund_payment(
                credentials={},
                payment_reference="missing",
                amount_minor=100,
                currency="USD",
                reason="requested_by_customer",
                idempotency_key="k1",
                timeout_seconds=5,
            )


class TestFakeCalendarAndNotificationProbes:
    def test_calendar_probe_is_a_no_op_success(self):
        FakeCalendarProvider().probe(credentials={}, timeout_seconds=5)

    def test_notification_probe_is_a_no_op_success(self):
        FakeNotificationProvider().probe(credentials={}, timeout_seconds=5)


class TestMakeSlotHelper:
    def test_produces_a_future_slot_of_the_requested_duration(self):
        slot = make_slot(hours_from_now=3, duration_minutes=45)
        assert (slot.end - slot.start).total_seconds() == 45 * 60


class TestFakeOrderProvider:
    def test_get_order_success(self):
        order = NormalizedOrder(
            order_id="ord_1",
            external_order_id="ORD-1",
            status="processing",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            amount_minor=1000,
            currency="USD",
        )
        fake = FakeOrderProvider(orders={"ORD-1": order})
        result = fake.get_order(
            credentials={}, configuration={}, order_reference="ORD-1", timeout_seconds=5
        )
        assert result is order
        assert fake.get_order_call_count == 1

    def test_get_order_not_found(self):
        fake = FakeOrderProvider()
        with pytest.raises(OrderNotFoundError):
            fake.get_order(credentials={}, configuration={}, order_reference="x", timeout_seconds=5)

    def test_get_order_injected_error(self):
        fake = FakeOrderProvider(order_errors=[OrderNotFoundError("custom")])
        with pytest.raises(OrderNotFoundError):
            fake.get_order(credentials={}, configuration={}, order_reference="x", timeout_seconds=5)

    def test_get_shipment_success(self):
        shipment = NormalizedShipment(shipment_id="shp_1", order_id="ord_1", status="in_transit")
        fake = FakeOrderProvider(shipments={"TRK-1": shipment})
        result = fake.get_shipment(
            credentials={}, configuration={}, shipment_reference="TRK-1", timeout_seconds=5
        )
        assert result is shipment
        assert fake.get_shipment_call_count == 1

    def test_get_shipment_not_found(self):
        fake = FakeOrderProvider()
        with pytest.raises(ShipmentNotFoundError):
            fake.get_shipment(
                credentials={}, configuration={}, shipment_reference="x", timeout_seconds=5
            )

    def test_get_shipment_injected_error(self):
        fake = FakeOrderProvider(shipment_errors=[ShipmentNotFoundError("custom")])
        with pytest.raises(ShipmentNotFoundError):
            fake.get_shipment(
                credentials={}, configuration={}, shipment_reference="x", timeout_seconds=5
            )
