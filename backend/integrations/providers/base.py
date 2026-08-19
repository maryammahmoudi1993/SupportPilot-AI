"""Project-owned typed provider protocols and normalized result types.

Every business tool depends on these — never on a vendor SDK type. Real
adapters (``integrations.providers.stripe_provider``,
``integrations.providers.google_calendar``) and fakes
(``integrations.providers.fakes``) both implement these structurally
(``Protocol``, ``@runtime_checkable``), so business services never know
which one they're talking to except through dependency injection
(section 8, 111-112).

Every operation takes ``credentials`` (a decrypted, short-lived plaintext
dict — never persisted, never logged) and ``timeout_seconds`` (the
*provider-level* network timeout, always <= the Phase 6 tool execution
timeout — section 74-75) explicitly, so no adapter can reach for global
state or an unbounded default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

# --------------------------------------------------------------------------
# Normalized result types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedPayment:
    payment_id: str
    external_payment_id: str
    status: str  # succeeded | pending | failed | refunded | partially_refunded
    amount_minor: int
    currency: str
    created_at: datetime
    refunded_amount_minor: int = 0
    provider_request_id: str | None = None


@dataclass(frozen=True)
class NormalizedRefund:
    refund_id: str
    payment_id: str
    status: str  # succeeded | pending | failed
    amount_minor: int
    currency: str
    created_at: datetime
    provider_request_id: str | None = None


@dataclass(frozen=True)
class AvailabilitySlot:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class NormalizedBooking:
    booking_id: str
    external_event_id: str
    start: datetime
    end: datetime
    status: str  # confirmed | cancelled
    provider_request_id: str | None = None


@dataclass(frozen=True)
class NormalizedNotification:
    message_id: str
    status: str  # sent | queued
    provider_request_id: str | None = None


@dataclass(frozen=True)
class NormalizedOrder:
    order_id: str
    external_order_id: str
    status: str  # processing | shipped | delivered | cancelled
    created_at: datetime
    amount_minor: int
    currency: str
    shipment_status: str | None = None
    tracking_reference: str | None = None


@dataclass(frozen=True)
class NormalizedShipment:
    shipment_id: str
    order_id: str
    status: str  # label_created | in_transit | delayed | delivered | returned
    tracking_reference: str | None = None
    carrier: str | None = None
    estimated_delivery: datetime | None = None


# --------------------------------------------------------------------------
# Provider protocols
# --------------------------------------------------------------------------


@runtime_checkable
class PaymentProvider(Protocol):
    name: str

    def get_payment(
        self, *, credentials: dict, payment_reference: str, timeout_seconds: float
    ) -> NormalizedPayment: ...

    def refund_payment(
        self,
        *,
        credentials: dict,
        payment_reference: str,
        amount_minor: int,
        currency: str,
        reason: str,
        idempotency_key: str,
        timeout_seconds: float,
    ) -> NormalizedRefund: ...


@runtime_checkable
class CalendarProvider(Protocol):
    name: str

    def get_availability(
        self,
        *,
        credentials: dict,
        configuration: dict,
        window_start: datetime,
        window_end: datetime,
        timeout_seconds: float,
    ) -> list[AvailabilitySlot]: ...

    def create_booking(
        self,
        *,
        credentials: dict,
        configuration: dict,
        start: datetime,
        end: datetime,
        title: str,
        attendee_email: str | None,
        idempotency_key: str,
        timeout_seconds: float,
    ) -> NormalizedBooking: ...


@runtime_checkable
class NotificationProvider(Protocol):
    name: str

    def send(
        self,
        *,
        credentials: dict,
        configuration: dict,
        recipient_email: str,
        subject: str,
        body: str,
        idempotency_key: str,
        timeout_seconds: float,
    ) -> NormalizedNotification: ...


@runtime_checkable
class OrderProvider(Protocol):
    name: str

    def get_order(
        self,
        *,
        credentials: dict,
        configuration: dict,
        order_reference: str,
        timeout_seconds: float,
    ) -> NormalizedOrder: ...

    def get_shipment(
        self,
        *,
        credentials: dict,
        configuration: dict,
        shipment_reference: str,
        timeout_seconds: float,
    ) -> NormalizedShipment: ...
