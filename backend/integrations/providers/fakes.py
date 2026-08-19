"""Deterministic, offline provider fakes for tests and default CI (section 25).

Every fake implements the same ``integrations.providers.base`` protocol a
real adapter does — application/service code never knows which one it has
(section 111). Scenario configuration is always explicit constructor state,
never a magic string embedded in a business argument.

Duplicate-protection / idempotency is modeled the same way a real provider's
idempotency key works: a repeated call with the same ``idempotency_key``
returns the previously recorded result without incrementing the "external
call" counter used by concurrency/duplication tests (section 42, 50, 91,
94). ``committed_before_raising=True`` on an injected error models a
provider that *did* process the side effect but the client only observed a
timeout/error — the ambiguous-outcome scenario in section 43/92.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from django.utils import timezone

from ..errors import (
    CalendarSlotUnavailableError,
    IntegrationError,
    OrderNotFoundError,
    PaymentNotFoundError,
    RefundNotAllowedByProviderError,
    ShipmentNotFoundError,
)
from .base import (
    AvailabilitySlot,
    NormalizedBooking,
    NormalizedNotification,
    NormalizedOrder,
    NormalizedPayment,
    NormalizedRefund,
    NormalizedShipment,
)


class FakePaymentProvider:
    """Deterministic ``PaymentProvider``. Seed ``payments`` keyed by the
    reference a lookup/refund will be called with."""

    name = "fake_payment"

    def __init__(
        self,
        *,
        payments: dict[str, NormalizedPayment] | None = None,
        get_payment_errors: list[IntegrationError] | None = None,
        refund_errors: list[tuple[IntegrationError, bool]] | None = None,
        probe_error: IntegrationError | None = None,
    ) -> None:
        self._payments = dict(payments or {})
        self._get_payment_errors = list(get_payment_errors or [])
        self._refund_errors = list(refund_errors or [])
        self._probe_error = probe_error
        self.get_payment_call_count = 0
        self.refund_call_count = 0
        self._refunds_by_key: dict[str, NormalizedRefund] = {}

    def probe(self, *, credentials: dict, timeout_seconds: float) -> None:
        """Read-only connection-test probe (section 68-69) — never mutates
        provider state."""
        if self._probe_error is not None:
            raise self._probe_error
        return None

    def get_payment(
        self, *, credentials: dict, payment_reference: str, timeout_seconds: float
    ) -> NormalizedPayment:
        self.get_payment_call_count += 1
        if self._get_payment_errors:
            raise self._get_payment_errors.pop(0)
        payment = self._payments.get(payment_reference)
        if payment is None:
            raise PaymentNotFoundError()
        return payment

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
    ) -> NormalizedRefund:
        existing = self._refunds_by_key.get(idempotency_key)
        if existing is not None:
            return existing

        self.refund_call_count += 1
        if self._refund_errors:
            error, committed_before_raising = self._refund_errors.pop(0)
            if committed_before_raising:
                self._commit_refund(
                    idempotency_key=idempotency_key,
                    payment_reference=payment_reference,
                    amount_minor=amount_minor,
                    currency=currency,
                )
            raise error

        payment = self._payments.get(payment_reference)
        if payment is None:
            raise PaymentNotFoundError()
        refundable = payment.amount_minor - payment.refunded_amount_minor
        if amount_minor > refundable:
            raise RefundNotAllowedByProviderError("Refund amount exceeds refundable balance.")
        return self._commit_refund(
            idempotency_key=idempotency_key,
            payment_reference=payment_reference,
            amount_minor=amount_minor,
            currency=currency,
        )

    def _commit_refund(
        self, *, idempotency_key: str, payment_reference: str, amount_minor: int, currency: str
    ) -> NormalizedRefund:
        payment = self._payments[payment_reference]
        refund = NormalizedRefund(
            refund_id=f"re_fake_{idempotency_key}",
            payment_id=payment.payment_id,
            status="succeeded",
            amount_minor=amount_minor,
            currency=currency,
            created_at=timezone.now(),
            provider_request_id=f"req_fake_{idempotency_key}",
        )
        self._refunds_by_key[idempotency_key] = refund
        new_refunded = payment.refunded_amount_minor + amount_minor
        self._payments[payment_reference] = dataclasses.replace(
            payment,
            refunded_amount_minor=new_refunded,
            status="refunded" if new_refunded >= payment.amount_minor else "partially_refunded",
        )
        return refund


class FakeCalendarProvider:
    """Deterministic ``CalendarProvider``. ``busy_slots`` seeds pre-existing
    conflicts; availability is whatever remains in the queried window."""

    name = "fake_calendar"

    def __init__(
        self,
        *,
        busy_slots: list[AvailabilitySlot] | None = None,
        availability_errors: list[IntegrationError] | None = None,
        booking_errors: list[tuple[IntegrationError, bool]] | None = None,
    ) -> None:
        self._busy_slots = list(busy_slots or [])
        self._availability_errors = list(availability_errors or [])
        self._booking_errors = list(booking_errors or [])
        self.get_availability_call_count = 0
        self.create_booking_call_count = 0
        self._bookings_by_key: dict[str, NormalizedBooking] = {}

    def probe(self, *, credentials: dict, timeout_seconds: float) -> None:
        return None

    def get_availability(
        self,
        *,
        credentials: dict,
        configuration: dict,
        window_start: datetime,
        window_end: datetime,
        timeout_seconds: float,
    ) -> list[AvailabilitySlot]:
        self.get_availability_call_count += 1
        if self._availability_errors:
            raise self._availability_errors.pop(0)
        if any(slot.start < window_end and slot.end > window_start for slot in self._busy_slots):
            return []
        return [AvailabilitySlot(start=window_start, end=window_end)]

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
    ) -> NormalizedBooking:
        existing = self._bookings_by_key.get(idempotency_key)
        if existing is not None:
            return existing

        self.create_booking_call_count += 1
        if self._booking_errors:
            error, committed_before_raising = self._booking_errors.pop(0)
            if committed_before_raising:
                self._commit_booking(idempotency_key=idempotency_key, start=start, end=end)
            raise error

        if any(slot.start < end and slot.end > start for slot in self._busy_slots):
            raise CalendarSlotUnavailableError()
        return self._commit_booking(idempotency_key=idempotency_key, start=start, end=end)

    def _commit_booking(
        self, *, idempotency_key: str, start: datetime, end: datetime
    ) -> NormalizedBooking:
        booking = NormalizedBooking(
            booking_id=f"bk_fake_{idempotency_key}",
            external_event_id=f"evt_fake_{idempotency_key}",
            start=start,
            end=end,
            status="confirmed",
            provider_request_id=f"req_fake_{idempotency_key}",
        )
        self._bookings_by_key[idempotency_key] = booking
        self._busy_slots.append(AvailabilitySlot(start=start, end=end))
        return booking


class FakeNotificationProvider:
    """Deterministic ``NotificationProvider``."""

    name = "fake_notification"

    def __init__(self, *, send_errors: list[tuple[IntegrationError, bool]] | None = None) -> None:
        self._send_errors = list(send_errors or [])
        self.send_call_count = 0
        self._sent_by_key: dict[str, NormalizedNotification] = {}
        #: Every message actually "delivered" — inspectable in tests instead
        #: of asserting against real outbound network traffic.
        self.outbox: list[dict] = []

    def probe(self, *, credentials: dict, timeout_seconds: float) -> None:
        return None

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
    ) -> NormalizedNotification:
        existing = self._sent_by_key.get(idempotency_key)
        if existing is not None:
            return existing

        self.send_call_count += 1
        if self._send_errors:
            error, committed_before_raising = self._send_errors.pop(0)
            if committed_before_raising:
                self._commit_send(idempotency_key, recipient_email, subject, body)
            raise error

        return self._commit_send(idempotency_key, recipient_email, subject, body)

    def _commit_send(
        self, idempotency_key: str, recipient_email: str, subject: str, body: str
    ) -> NormalizedNotification:
        message = NormalizedNotification(
            message_id=f"msg_fake_{idempotency_key}",
            status="sent",
            provider_request_id=f"req_fake_{idempotency_key}",
        )
        self._sent_by_key[idempotency_key] = message
        self.outbox.append({"to": recipient_email, "subject": subject, "body": body})
        return message


class FakeOrderProvider:
    """Deterministic ``OrderProvider`` used for provider-boundary contract
    tests. ``integrations.providers.demo_commerce.DemoCommerceProvider`` is
    the adapter actually wired up for the ``order.lookup``/``shipment.lookup``
    tools (section 30) — this fake exists to exercise error-path contracts
    the same way ``FakePaymentProvider``/``FakeCalendarProvider`` do."""

    name = "fake_order"

    def __init__(
        self,
        *,
        orders: dict[str, NormalizedOrder] | None = None,
        shipments: dict[str, NormalizedShipment] | None = None,
        order_errors: list[IntegrationError] | None = None,
        shipment_errors: list[IntegrationError] | None = None,
    ) -> None:
        self._orders = dict(orders or {})
        self._shipments = dict(shipments or {})
        self._order_errors = list(order_errors or [])
        self._shipment_errors = list(shipment_errors or [])
        self.get_order_call_count = 0
        self.get_shipment_call_count = 0

    def get_order(
        self,
        *,
        credentials: dict,
        configuration: dict,
        order_reference: str,
        timeout_seconds: float,
    ) -> NormalizedOrder:
        self.get_order_call_count += 1
        if self._order_errors:
            raise self._order_errors.pop(0)
        order = self._orders.get(order_reference)
        if order is None:
            raise OrderNotFoundError()
        return order

    def get_shipment(
        self,
        *,
        credentials: dict,
        configuration: dict,
        shipment_reference: str,
        timeout_seconds: float,
    ) -> NormalizedShipment:
        self.get_shipment_call_count += 1
        if self._shipment_errors:
            raise self._shipment_errors.pop(0)
        shipment = self._shipments.get(shipment_reference)
        if shipment is None:
            raise ShipmentNotFoundError()
        return shipment


def make_slot(*, hours_from_now: int, duration_minutes: int = 30) -> AvailabilitySlot:
    """Test helper: a deterministic slot relative to "now" for calendar fakes."""
    start = timezone.now() + timedelta(hours=hours_from_now)
    return AvailabilitySlot(start=start, end=start + timedelta(minutes=duration_minutes))
