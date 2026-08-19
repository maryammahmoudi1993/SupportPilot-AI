"""Typed per-provider credential and configuration schemas (section 136-137).

Nothing accepts arbitrary unvalidated secret JSON: every provider has an
explicit ``pydantic`` model for both its secret ``credentials`` and its
non-secret ``configuration``. ``schema_version`` is carried so a future
migration can detect and upgrade an older stored shape (section 137).
"""

from __future__ import annotations

from typing import Annotated, Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from .errors import IntegrationConfigurationError
from .models import IntegrationProvider


def _validate_email_str(value: str) -> str:
    try:
        validate_email(value)
    except DjangoValidationError as exc:
        raise ValueError("Not a valid email address.") from exc
    return value


# Django's own validator (no extra dependency) rather than pydantic's
# ``EmailStr``, which requires the optional ``email-validator`` package
# that is not part of this project's pinned dependencies.
EmailAddress = Annotated[str, AfterValidator(_validate_email_str)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Credentials (secret) ----------------------------------------------------


class StripeCredentials(StrictModel):
    schema_version: int = 1
    secret_key: str = Field(min_length=8, max_length=500)


class GoogleCalendarCredentials(StrictModel):
    schema_version: int = 1
    service_account_info: dict[str, Any]


class SmtpCredentials(StrictModel):
    schema_version: int = 1
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535, default=587)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=500)
    use_tls: bool = True


class DemoCommerceCredentials(StrictModel):
    """No secrets required — present only so every provider has a uniform
    credential envelope and ``credentials_configured`` behaves consistently."""

    schema_version: int = 1


CREDENTIAL_SCHEMAS: dict[str, type[StrictModel]] = {
    IntegrationProvider.STRIPE: StripeCredentials,
    IntegrationProvider.GOOGLE_CALENDAR: GoogleCalendarCredentials,
    IntegrationProvider.EMAIL: SmtpCredentials,
    IntegrationProvider.DEMO_COMMERCE: DemoCommerceCredentials,
}


# --- Configuration (non-secret) ---------------------------------------------


class StripeConfiguration(StrictModel):
    pass


class GoogleCalendarConfiguration(StrictModel):
    calendar_id: str = Field(default="primary", max_length=255)


class EmailConfiguration(StrictModel):
    from_email: EmailAddress


class DemoCommerceConfiguration(StrictModel):
    orders: dict[str, dict[str, Any]] = Field(default_factory=dict)
    shipments: dict[str, dict[str, Any]] = Field(default_factory=dict)


CONFIGURATION_SCHEMAS: dict[str, type[StrictModel]] = {
    IntegrationProvider.STRIPE: StripeConfiguration,
    IntegrationProvider.GOOGLE_CALENDAR: GoogleCalendarConfiguration,
    IntegrationProvider.EMAIL: EmailConfiguration,
    IntegrationProvider.DEMO_COMMERCE: DemoCommerceConfiguration,
}


def validate_credentials(*, provider: str, data: dict[str, Any]) -> dict[str, Any]:
    schema = CREDENTIAL_SCHEMAS.get(provider)
    if schema is None:
        raise IntegrationConfigurationError(f"No credential schema for provider {provider!r}.")
    try:
        validated = schema.model_validate(data)
    except Exception as exc:
        raise IntegrationConfigurationError("Credentials failed validation.") from exc
    return validated.model_dump(mode="json")


def validate_configuration(*, provider: str, data: dict[str, Any]) -> dict[str, Any]:
    schema = CONFIGURATION_SCHEMAS.get(provider)
    if schema is None:
        raise IntegrationConfigurationError(f"No configuration schema for provider {provider!r}.")
    try:
        validated = schema.model_validate(data or {})
    except Exception as exc:
        raise IntegrationConfigurationError("Configuration failed validation.") from exc
    return validated.model_dump(mode="json")
