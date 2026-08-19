"""Typed provider credential/configuration schema tests (section 136-137)."""

from __future__ import annotations

import pytest

from integrations.errors import IntegrationConfigurationError
from integrations.schemas import validate_configuration, validate_credentials


class TestUnknownProvider:
    def test_validate_credentials_rejects_unknown_provider(self):
        with pytest.raises(IntegrationConfigurationError):
            validate_credentials(provider="not_a_real_provider", data={})

    def test_validate_configuration_rejects_unknown_provider(self):
        with pytest.raises(IntegrationConfigurationError):
            validate_configuration(provider="not_a_real_provider", data={})


class TestEmailConfiguration:
    def test_invalid_from_email_is_rejected(self):
        with pytest.raises(IntegrationConfigurationError):
            validate_configuration(provider="email", data={"from_email": "not-an-email"})

    def test_valid_from_email_is_accepted(self):
        result = validate_configuration(
            provider="email", data={"from_email": "support@example.com"}
        )
        assert result["from_email"] == "support@example.com"
