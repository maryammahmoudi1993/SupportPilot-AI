"""Provider resolution: fake-by-default, live-opt-in, unknown-provider
rejection (section 25-26, 112, 139-140)."""

from __future__ import annotations

import pytest

from integrations.errors import IntegrationProviderNotSupportedError
from integrations.models import IntegrationProvider
from integrations.providers import factory
from integrations.providers.demo_commerce import DemoCommerceProvider
from integrations.providers.fakes import (
    FakeCalendarProvider,
    FakeNotificationProvider,
    FakePaymentProvider,
)


class TestDefaultIsAlwaysFake:
    def test_payment_provider_defaults_to_fake(self, settings):
        settings.INTEGRATIONS_LIVE_PROVIDERS_ENABLED = False
        assert isinstance(
            factory.get_payment_provider(provider=IntegrationProvider.STRIPE), FakePaymentProvider
        )

    def test_calendar_provider_defaults_to_fake(self, settings):
        settings.INTEGRATIONS_LIVE_PROVIDERS_ENABLED = False
        assert isinstance(
            factory.get_calendar_provider(provider=IntegrationProvider.GOOGLE_CALENDAR),
            FakeCalendarProvider,
        )

    def test_notification_provider_defaults_to_fake(self, settings):
        settings.INTEGRATIONS_LIVE_PROVIDERS_ENABLED = False
        assert isinstance(
            factory.get_notification_provider(provider=IntegrationProvider.EMAIL),
            FakeNotificationProvider,
        )

    def test_order_provider_is_always_the_demo_adapter(self, settings):
        # No live vendor exists for orders/shipments (section 30) — this is
        # unaffected by INTEGRATIONS_LIVE_PROVIDERS_ENABLED either way.
        settings.INTEGRATIONS_LIVE_PROVIDERS_ENABLED = True
        assert isinstance(
            factory.get_order_provider(provider=IntegrationProvider.DEMO_COMMERCE),
            DemoCommerceProvider,
        )


class TestLiveOptIn:
    def test_payment_provider_is_real_when_enabled(self, settings):
        settings.INTEGRATIONS_LIVE_PROVIDERS_ENABLED = True
        from integrations.providers.stripe_provider import StripePaymentProvider

        assert isinstance(
            factory.get_payment_provider(provider=IntegrationProvider.STRIPE), StripePaymentProvider
        )

    def test_calendar_provider_is_real_when_enabled(self, settings):
        settings.INTEGRATIONS_LIVE_PROVIDERS_ENABLED = True
        from integrations.providers.google_calendar import GoogleCalendarProvider

        assert isinstance(
            factory.get_calendar_provider(provider=IntegrationProvider.GOOGLE_CALENDAR),
            GoogleCalendarProvider,
        )

    def test_notification_provider_is_real_when_enabled(self, settings):
        settings.INTEGRATIONS_LIVE_PROVIDERS_ENABLED = True
        from integrations.providers.email_provider import SmtpNotificationProvider

        assert isinstance(
            factory.get_notification_provider(provider=IntegrationProvider.EMAIL),
            SmtpNotificationProvider,
        )


class TestUnsupportedProvider:
    def test_payment_provider_rejects_unknown_provider(self):
        with pytest.raises(IntegrationProviderNotSupportedError):
            factory.get_payment_provider(provider=IntegrationProvider.GOOGLE_CALENDAR)

    def test_calendar_provider_rejects_unknown_provider(self):
        with pytest.raises(IntegrationProviderNotSupportedError):
            factory.get_calendar_provider(provider=IntegrationProvider.STRIPE)

    def test_notification_provider_rejects_unknown_provider(self):
        with pytest.raises(IntegrationProviderNotSupportedError):
            factory.get_notification_provider(provider=IntegrationProvider.STRIPE)

    def test_order_provider_rejects_unknown_provider(self):
        with pytest.raises(IntegrationProviderNotSupportedError):
            factory.get_order_provider(provider=IntegrationProvider.STRIPE)
