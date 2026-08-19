"""Connection management service tests: creation, rotation, enable/disable,
health tracking, and the two-layer timeout rule (section 11-18, 74-77,
113-117)."""

from __future__ import annotations

import pytest

from accounts.tests.factories import UserFactory
from integrations import services
from integrations.crypto import decrypt_credentials
from integrations.errors import (
    IntegrationAuthenticationFailedError,
    IntegrationConfigurationError,
    IntegrationDisabledError,
    IntegrationNotConfiguredError,
    IntegrationRateLimitedError,
)
from integrations.models import IntegrationConnectionStatus, IntegrationProvider
from integrations.providers.fakes import FakePaymentProvider
from workspaces.tests.factories import WorkspaceFactory

from .factories import IntegrationConnectionFactory


@pytest.mark.django_db
class TestCreateConnection:
    def test_creates_active_connection_with_encrypted_credentials(self):
        workspace = WorkspaceFactory()
        actor = UserFactory()
        connection = services.create_connection(
            workspace=workspace,
            actor=actor,
            provider=IntegrationProvider.STRIPE,
            display_name="Prod Stripe",
            environment="test",
            credentials={"secret_key": "sk_test_abc123"},
        )
        assert connection.status == IntegrationConnectionStatus.ACTIVE
        assert connection.encrypted_credentials
        assert "sk_test_abc123" not in connection.encrypted_credentials
        assert (
            decrypt_credentials(connection.encrypted_credentials)["secret_key"] == "sk_test_abc123"
        )

    def test_rejects_invalid_credential_schema(self):
        workspace = WorkspaceFactory()
        with pytest.raises(IntegrationConfigurationError):
            services.create_connection(
                workspace=workspace,
                actor=UserFactory(),
                provider=IntegrationProvider.STRIPE,
                display_name="",
                environment="test",
                credentials={"unexpected_field": "x"},
            )

    def test_rejects_unknown_configuration_field(self):
        workspace = WorkspaceFactory()
        with pytest.raises(IntegrationConfigurationError):
            services.create_connection(
                workspace=workspace,
                actor=UserFactory(),
                provider=IntegrationProvider.STRIPE,
                display_name="",
                environment="test",
                credentials={"secret_key": "sk_test_abc123"},
                configuration={"not_a_real_field": True},
            )


@pytest.mark.django_db
class TestUpdateConnectionConfiguration:
    def test_updates_display_name_and_configuration(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.GOOGLE_CALENDAR)
        updated = services.update_connection_configuration(
            workspace=connection.workspace,
            connection=connection,
            actor=UserFactory(),
            display_name="New name",
            configuration={"calendar_id": "team@example.com"},
        )
        assert updated.display_name == "New name"
        assert updated.configuration == {"calendar_id": "team@example.com"}

    def test_partial_update_leaves_other_fields_untouched(self):
        connection = IntegrationConnectionFactory(
            provider=IntegrationProvider.GOOGLE_CALENDAR,
            display_name="Original",
            configuration={"calendar_id": "primary"},
        )
        services.update_connection_configuration(
            workspace=connection.workspace, connection=connection, actor=UserFactory()
        )
        connection.refresh_from_db()
        assert connection.display_name == "Original"
        assert connection.configuration == {"calendar_id": "primary"}


@pytest.mark.django_db
class TestRotateCredentials:
    def test_rotation_replaces_ciphertext_and_bumps_version(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        old_ciphertext = connection.encrypted_credentials
        updated = services.rotate_credentials(
            workspace=connection.workspace,
            connection=connection,
            actor=UserFactory(),
            credentials={"secret_key": "sk_test_new_key"},
        )
        assert updated.encrypted_credentials != old_ciphertext
        assert updated.credential_version == 2
        assert decrypt_credentials(updated.encrypted_credentials)["secret_key"] == "sk_test_new_key"

    def test_failed_validation_leaves_old_credentials_intact(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        old_ciphertext = connection.encrypted_credentials
        with pytest.raises(IntegrationConfigurationError):
            services.rotate_credentials(
                workspace=connection.workspace,
                connection=connection,
                actor=UserFactory(),
                credentials={"bogus": True},
            )
        connection.refresh_from_db()
        assert connection.encrypted_credentials == old_ciphertext

    def test_rotation_clears_invalid_credentials_status(self):
        connection = IntegrationConnectionFactory(
            provider=IntegrationProvider.STRIPE,
            status=IntegrationConnectionStatus.INVALID_CREDENTIALS,
        )
        updated = services.rotate_credentials(
            workspace=connection.workspace,
            connection=connection,
            actor=UserFactory(),
            credentials={"secret_key": "sk_test_new_key"},
        )
        assert updated.status == IntegrationConnectionStatus.ACTIVE


@pytest.mark.django_db
class TestEnableDisable:
    def test_disable_blocks_business_operations_before_any_provider_call(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        services.set_connection_enabled(
            workspace=connection.workspace,
            connection=connection,
            actor=UserFactory(),
            enabled=False,
        )
        fake = FakePaymentProvider()
        with pytest.raises(IntegrationDisabledError):
            services.get_payment(
                workspace=connection.workspace,
                remaining_seconds=5,
                payment_reference="pi_1",
                payment_provider=fake,
            )
        assert fake.get_payment_call_count == 0

    def test_no_connection_at_all_is_not_configured(self):
        workspace = WorkspaceFactory()
        with pytest.raises(IntegrationNotConfiguredError):
            services.get_payment(workspace=workspace, remaining_seconds=5, payment_reference="pi_1")

    def test_connection_without_credentials_configured_is_not_configured(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        connection.encrypted_credentials = ""
        connection.save(update_fields=["encrypted_credentials"])
        with pytest.raises(IntegrationNotConfiguredError):
            services.get_payment(
                workspace=connection.workspace, remaining_seconds=5, payment_reference="pi_1"
            )


@pytest.mark.django_db
class TestProbeProviderResolution:
    @pytest.mark.parametrize(
        "provider,expected_type",
        [
            (IntegrationProvider.STRIPE, "FakePaymentProvider"),
            (IntegrationProvider.GOOGLE_CALENDAR, "FakeCalendarProvider"),
            (IntegrationProvider.EMAIL, "FakeNotificationProvider"),
            (IntegrationProvider.DEMO_COMMERCE, "DemoCommerceProvider"),
        ],
    )
    def test_resolves_a_probe_capable_provider_for_every_provider_type(
        self, provider, expected_type
    ):
        resolved = services._resolve_probe_provider(provider)
        assert type(resolved).__name__ == expected_type
        assert hasattr(resolved, "probe")


@pytest.mark.django_db
class TestConnectionHealth:
    def test_auth_failure_marks_invalid_credentials_not_merely_degraded(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        fake = FakePaymentProvider(get_payment_errors=[IntegrationAuthenticationFailedError()])
        with pytest.raises(IntegrationAuthenticationFailedError):
            services.get_payment(
                workspace=connection.workspace,
                remaining_seconds=5,
                payment_reference="pi_1",
                payment_provider=fake,
            )
        connection.refresh_from_db()
        assert connection.status == IntegrationConnectionStatus.INVALID_CREDENTIALS
        assert connection.last_error_code == "integration_authentication_failed"

    def test_transient_failure_marks_degraded_not_invalid_credentials(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        fake = FakePaymentProvider(get_payment_errors=[IntegrationRateLimitedError()])
        with pytest.raises(IntegrationRateLimitedError):
            services.get_payment(
                workspace=connection.workspace,
                remaining_seconds=5,
                payment_reference="pi_1",
                payment_provider=fake,
            )
        connection.refresh_from_db()
        assert connection.status == IntegrationConnectionStatus.DEGRADED

    def test_success_after_degraded_returns_to_active(self):
        connection = IntegrationConnectionFactory(
            provider=IntegrationProvider.STRIPE, status=IntegrationConnectionStatus.DEGRADED
        )
        from datetime import UTC, datetime

        from integrations.providers.base import NormalizedPayment

        fake = FakePaymentProvider(
            payments={
                "pi_1": NormalizedPayment(
                    payment_id="pi_1",
                    external_payment_id="pi_1",
                    status="succeeded",
                    amount_minor=1000,
                    currency="USD",
                    created_at=datetime(2024, 1, 1, tzinfo=UTC),
                )
            }
        )
        services.get_payment(
            workspace=connection.workspace,
            remaining_seconds=5,
            payment_reference="pi_1",
            payment_provider=fake,
        )
        connection.refresh_from_db()
        assert connection.status == IntegrationConnectionStatus.ACTIVE
        assert connection.last_success_at is not None
        assert connection.last_error_code == ""

    def test_corrupt_ciphertext_becomes_configuration_error_not_a_crash(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        connection.encrypted_credentials = "not-a-valid-token"
        connection.save(update_fields=["encrypted_credentials"])
        with pytest.raises(IntegrationConfigurationError):
            services.get_payment(
                workspace=connection.workspace, remaining_seconds=5, payment_reference="pi_1"
            )


@pytest.mark.django_db
class TestEffectiveProviderTimeout:
    def test_never_exceeds_configured_max(self, settings):
        settings.INTEGRATIONS_MAX_TIMEOUT_SECONDS = 3.0
        settings.INTEGRATIONS_DEFAULT_TIMEOUT_SECONDS = 3.0
        assert services.effective_provider_timeout(100.0) == 3.0

    def test_leaves_a_margin_under_the_remaining_tool_deadline(self, settings):
        settings.INTEGRATIONS_DEFAULT_TIMEOUT_SECONDS = 30.0
        settings.INTEGRATIONS_MAX_TIMEOUT_SECONDS = 30.0
        timeout = services.effective_provider_timeout(2.0)
        assert timeout < 2.0

    def test_never_below_the_minimum_floor(self):
        assert services.effective_provider_timeout(0.0) == services.MIN_PROVIDER_TIMEOUT_SECONDS
