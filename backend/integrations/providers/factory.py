"""Deterministic provider resolution (section 112, 139-140).

Dispatches on ``IntegrationConnection.provider`` only — never on a database
or model-supplied import path/class name. Real, side-effecting adapters
(Stripe, Google Calendar, SMTP) are only ever constructed when
``settings.INTEGRATIONS_LIVE_PROVIDERS_ENABLED`` is true; every normal
test/CI/default-dev path gets the deterministic fake instead (section 25-26).

Test code that wants a specific fake instance (to assert call counts, seed
scenarios, inspect an outbox, ...) should construct one directly and pass it
to a service function via dependency injection rather than going through
this factory — this module exists for the one real runtime call site.
"""

from __future__ import annotations

from django.conf import settings

from ..errors import IntegrationProviderNotSupportedError
from ..models import IntegrationProvider
from .base import CalendarProvider, NotificationProvider, OrderProvider, PaymentProvider
from .demo_commerce import DemoCommerceProvider
from .fakes import FakeCalendarProvider, FakeNotificationProvider, FakePaymentProvider


def _live_enabled() -> bool:
    return bool(getattr(settings, "INTEGRATIONS_LIVE_PROVIDERS_ENABLED", False))


def get_payment_provider(*, provider: str) -> PaymentProvider:
    if provider != IntegrationProvider.STRIPE:
        raise IntegrationProviderNotSupportedError(f"No payment provider for {provider!r}.")
    if _live_enabled():
        from .stripe_provider import StripePaymentProvider

        return StripePaymentProvider()
    return FakePaymentProvider()


def get_calendar_provider(*, provider: str) -> CalendarProvider:
    if provider != IntegrationProvider.GOOGLE_CALENDAR:
        raise IntegrationProviderNotSupportedError(f"No calendar provider for {provider!r}.")
    if _live_enabled():
        from .google_calendar import GoogleCalendarProvider

        return GoogleCalendarProvider()
    return FakeCalendarProvider()


def get_notification_provider(*, provider: str) -> NotificationProvider:
    if provider != IntegrationProvider.EMAIL:
        raise IntegrationProviderNotSupportedError(f"No notification provider for {provider!r}.")
    if _live_enabled():
        from .email_provider import SmtpNotificationProvider

        return SmtpNotificationProvider()
    return FakeNotificationProvider()


def get_order_provider(*, provider: str) -> OrderProvider:
    if provider != IntegrationProvider.DEMO_COMMERCE:
        raise IntegrationProviderNotSupportedError(f"No order provider for {provider!r}.")
    # Always the deterministic demo adapter — there is no real vendor to
    # gate behind INTEGRATIONS_LIVE_PROVIDERS_ENABLED (section 30).
    return DemoCommerceProvider()
