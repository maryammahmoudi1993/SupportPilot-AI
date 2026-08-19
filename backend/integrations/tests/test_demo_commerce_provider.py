"""``DemoCommerceProvider`` direct unit tests (section 30, 78)."""

from __future__ import annotations

import pytest

from integrations.errors import IntegrationMalformedResponseError
from integrations.providers.demo_commerce import DemoCommerceProvider


@pytest.fixture
def provider() -> DemoCommerceProvider:
    return DemoCommerceProvider()


class TestProbe:
    def test_probe_is_a_no_op_success(self, provider):
        provider.probe(credentials={}, timeout_seconds=5)


class TestOrderMalformedData:
    def test_invalid_created_at_is_malformed_response(self, provider):
        configuration = {
            "orders": {
                "ORD-1": {
                    "status": "processing",
                    "created_at": "not-a-date",
                    "amount_minor": 100,
                    "currency": "usd",
                }
            }
        }
        with pytest.raises(IntegrationMalformedResponseError):
            provider.get_order(
                credentials={},
                configuration=configuration,
                order_reference="ORD-1",
                timeout_seconds=5,
            )


class TestShipmentMalformedData:
    def test_invalid_estimated_delivery_is_malformed_response(self, provider):
        configuration = {
            "shipments": {"TRK-1": {"status": "in_transit", "estimated_delivery": "not-a-date"}}
        }
        with pytest.raises(IntegrationMalformedResponseError):
            provider.get_shipment(
                credentials={},
                configuration=configuration,
                shipment_reference="TRK-1",
                timeout_seconds=5,
            )

    def test_valid_estimated_delivery_is_parsed(self, provider):
        configuration = {
            "shipments": {
                "TRK-1": {
                    "status": "in_transit",
                    "estimated_delivery": "2030-01-01T00:00:00+00:00",
                }
            }
        }
        shipment = provider.get_shipment(
            credentials={},
            configuration=configuration,
            shipment_reference="TRK-1",
            timeout_seconds=5,
        )
        assert shipment.estimated_delivery is not None
