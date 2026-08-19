"""The commerce/order-shipment provider actually wired to ``order.lookup``
and ``shipment.lookup`` (section 30).

The repository has no real order-management system yet, so this is a
deterministic, production-shaped adapter rather than a live vendor
integration — never presented as one. Its dataset comes entirely from the
owning ``IntegrationConnection.configuration`` (non-secret, admin-managed;
section 136), so a workspace's demo catalog is explicit, typed, and
inspectable rather than hardcoded globally.
"""

from __future__ import annotations

from datetime import datetime

from ..errors import IntegrationMalformedResponseError, OrderNotFoundError, ShipmentNotFoundError
from .base import NormalizedOrder, NormalizedShipment

#: Required shape of one ``configuration["orders"][<order_reference>]`` entry.
_REQUIRED_ORDER_FIELDS = frozenset({"status", "created_at", "amount_minor", "currency"})


class DemoCommerceProvider:
    """Deterministic ``OrderProvider``. No credentials or network calls —
    ``credentials`` is accepted only to satisfy the protocol shape; the
    catalog lives entirely in ``configuration``."""

    name = "demo_commerce"

    def probe(self, *, credentials: dict, timeout_seconds: float) -> None:
        return None

    def get_order(
        self,
        *,
        credentials: dict,
        configuration: dict,
        order_reference: str,
        timeout_seconds: float,
    ) -> NormalizedOrder:
        catalog = (configuration or {}).get("orders", {})
        raw = catalog.get(order_reference)
        if raw is None:
            raise OrderNotFoundError()
        if not _REQUIRED_ORDER_FIELDS.issubset(raw):
            raise IntegrationMalformedResponseError("Demo order catalog entry is incomplete.")
        try:
            created_at = datetime.fromisoformat(raw["created_at"])
        except (KeyError, ValueError) as exc:
            raise IntegrationMalformedResponseError("Demo order has an invalid timestamp.") from exc
        return NormalizedOrder(
            order_id=f"ord_{order_reference}",
            external_order_id=order_reference,
            status=raw["status"],
            created_at=created_at,
            amount_minor=int(raw["amount_minor"]),
            currency=str(raw["currency"]).upper(),
            shipment_status=raw.get("shipment_status"),
            tracking_reference=raw.get("tracking_reference"),
        )

    def get_shipment(
        self,
        *,
        credentials: dict,
        configuration: dict,
        shipment_reference: str,
        timeout_seconds: float,
    ) -> NormalizedShipment:
        catalog = (configuration or {}).get("shipments", {})
        raw = catalog.get(shipment_reference)
        if raw is None:
            raise ShipmentNotFoundError()
        estimated_delivery = None
        if raw.get("estimated_delivery"):
            try:
                estimated_delivery = datetime.fromisoformat(raw["estimated_delivery"])
            except ValueError as exc:
                raise IntegrationMalformedResponseError(
                    "Demo shipment has an invalid delivery timestamp."
                ) from exc
        return NormalizedShipment(
            shipment_id=f"shp_{shipment_reference}",
            order_id=raw.get("order_id", ""),
            status=raw.get("status", "label_created"),
            tracking_reference=raw.get("tracking_reference", shipment_reference),
            carrier=raw.get("carrier"),
            estimated_delivery=estimated_delivery,
        )
