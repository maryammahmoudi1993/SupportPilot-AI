"""``IntegrationConnection`` model invariants (section 71, 101)."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from integrations.models import IntegrationConnectionStatus, IntegrationProvider

from .factories import IntegrationConnectionFactory


@pytest.mark.django_db
class TestOnePerProviderConstraint:
    def test_second_connection_same_provider_same_workspace_rejected(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        with pytest.raises(IntegrityError), transaction.atomic():
            IntegrationConnectionFactory(
                workspace=connection.workspace, provider=IntegrationProvider.STRIPE
            )

    def test_same_provider_different_workspace_allowed(self):
        first = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        second = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        assert first.workspace_id != second.workspace_id

    def test_different_providers_same_workspace_allowed(self):
        first = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        second = IntegrationConnectionFactory(
            workspace=first.workspace, provider=IntegrationProvider.GOOGLE_CALENDAR
        )
        assert second.workspace_id == first.workspace_id


@pytest.mark.django_db
class TestSafeRepresentation:
    def test_str_never_includes_credential_material(self):
        connection = IntegrationConnectionFactory()
        assert "sk_test" not in str(connection)

    def test_credentials_configured_reflects_ciphertext_presence(self):
        connection = IntegrationConnectionFactory()
        assert connection.credentials_configured is True
        connection.encrypted_credentials = ""
        assert connection.credentials_configured is False

    def test_capabilities_are_derived_from_provider(self):
        connection = IntegrationConnectionFactory(provider=IntegrationProvider.STRIPE)
        assert connection.capabilities == frozenset({"payment_lookup", "refund"})

    def test_enabled_reflects_active_status_only(self):
        connection = IntegrationConnectionFactory(status=IntegrationConnectionStatus.DEGRADED)
        assert connection.enabled is False
        connection.status = IntegrationConnectionStatus.ACTIVE
        assert connection.enabled is True
