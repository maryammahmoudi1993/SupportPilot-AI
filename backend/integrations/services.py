"""Integration connection management and provider-facing business
operations (section 11-18, 64-77, 113-117).

Two responsibilities live here, kept in one module because they share the
same connection-resolution and credential-decryption boundary:

1. Connection CRUD used by the integrations management API (admin-only).
2. The narrow operations each business tool (``integrations.tools``) calls
   — resolve the workspace's connection for a provider, decrypt credentials
   immediately before use, bound the provider call with a two-layer
   timeout, normalize/re-raise provider errors, and record connection
   health. No tool handler talks to a provider adapter directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from workspaces.models import Workspace

from .crypto import CredentialEncryptionError, decrypt_credentials, encrypt_credentials
from .errors import (
    IntegrationAuthenticationFailedError,
    IntegrationConfigurationError,
    IntegrationDisabledError,
    IntegrationError,
    IntegrationNotConfiguredError,
    IntegrationPermissionDeniedError,
    IntegrationRateLimitedError,
    IntegrationTemporarilyUnavailableError,
    IntegrationTimeoutError,
)
from .models import IntegrationConnection, IntegrationConnectionStatus, IntegrationProvider
from .providers.base import (
    NormalizedBooking,
    NormalizedNotification,
    NormalizedOrder,
    NormalizedPayment,
    NormalizedRefund,
    NormalizedShipment,
)
from .providers.factory import (
    get_calendar_provider,
    get_notification_provider,
    get_order_provider,
    get_payment_provider,
)
from .schemas import validate_configuration, validate_credentials
from .selectors import resolve_connection_for_tool

T = TypeVar("T")

MIN_PROVIDER_TIMEOUT_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Connection management (admin API)
# ---------------------------------------------------------------------------


@transaction.atomic
def create_connection(
    *,
    workspace: Workspace,
    actor: User,
    provider: str,
    display_name: str,
    environment: str,
    credentials: dict[str, Any],
    configuration: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> IntegrationConnection:
    validated_credentials = validate_credentials(provider=provider, data=credentials)
    validated_configuration = validate_configuration(provider=provider, data=configuration or {})
    connection = IntegrationConnection(
        workspace=workspace,
        provider=provider,
        display_name=display_name or "",
        environment=environment,
        configuration=validated_configuration,
        created_by=actor,
        status=IntegrationConnectionStatus.ACTIVE,
    )
    connection.encrypted_credentials = encrypt_credentials(validated_credentials)
    connection.credential_version = 1
    connection.full_clean()
    connection.save()
    record_event(
        action=AuditAction.INTEGRATION_CONNECTION_CREATED,
        target_type="integration_connection",
        target_id=connection.id,
        actor=actor,
        workspace=workspace,
        metadata={"provider": provider, "environment": environment},
        request_id=request_id,
    )
    return connection


@transaction.atomic
def update_connection_configuration(
    *,
    workspace: Workspace,
    connection: IntegrationConnection,
    actor: User,
    display_name: str | None = None,
    configuration: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> IntegrationConnection:
    update_fields = ["updated_at"]
    if display_name is not None:
        connection.display_name = display_name
        update_fields.append("display_name")
    if configuration is not None:
        connection.configuration = validate_configuration(
            provider=connection.provider, data=configuration
        )
        update_fields.append("configuration")
    connection.save(update_fields=update_fields)
    record_event(
        action=AuditAction.INTEGRATION_CONNECTION_UPDATED,
        target_type="integration_connection",
        target_id=connection.id,
        actor=actor,
        workspace=workspace,
        metadata={"provider": connection.provider},
        request_id=request_id,
    )
    return connection


@transaction.atomic
def rotate_credentials(
    *,
    workspace: Workspace,
    connection: IntegrationConnection,
    actor: User,
    credentials: dict[str, Any],
    request_id: str | None = None,
) -> IntegrationConnection:
    """Replace stored credentials atomically. Validated/encrypted before the
    old ciphertext is touched, so a validation failure never leaves a
    half-updated row (section 18)."""
    validated = validate_credentials(provider=connection.provider, data=credentials)
    new_ciphertext = encrypt_credentials(validated)
    connection.encrypted_credentials = new_ciphertext
    connection.credential_version += 1
    connection.last_error_code = ""
    if connection.status == IntegrationConnectionStatus.INVALID_CREDENTIALS:
        connection.status = IntegrationConnectionStatus.ACTIVE
    connection.save(
        update_fields=[
            "encrypted_credentials",
            "credential_version",
            "last_error_code",
            "status",
            "updated_at",
        ]
    )
    record_event(
        action=AuditAction.INTEGRATION_CREDENTIALS_ROTATED,
        target_type="integration_connection",
        target_id=connection.id,
        actor=actor,
        workspace=workspace,
        metadata={
            "provider": connection.provider,
            "credential_version": connection.credential_version,
        },
        request_id=request_id,
    )
    return connection


@transaction.atomic
def set_connection_enabled(
    *,
    workspace: Workspace,
    connection: IntegrationConnection,
    actor: User,
    enabled: bool,
    request_id: str | None = None,
) -> IntegrationConnection:
    connection.status = (
        IntegrationConnectionStatus.ACTIVE if enabled else IntegrationConnectionStatus.DISABLED
    )
    connection.save(update_fields=["status", "updated_at"])
    record_event(
        action=(
            AuditAction.INTEGRATION_CONNECTION_ENABLED
            if enabled
            else AuditAction.INTEGRATION_CONNECTION_DISABLED
        ),
        target_type="integration_connection",
        target_id=connection.id,
        actor=actor,
        workspace=workspace,
        metadata={"provider": connection.provider},
        request_id=request_id,
    )
    return connection


def test_connection(
    *,
    workspace: Workspace,
    connection: IntegrationConnection,
    actor: User,
    request_id: str | None = None,
) -> dict[str, Any]:
    """A privileged, read-only probe (section 68-69, 141): never creates a
    refund/booking/send. Bounded timeout, normalized result, no credential
    return."""
    if connection.status == IntegrationConnectionStatus.DISABLED:
        raise IntegrationDisabledError()

    def _probe(credentials: dict[str, Any]) -> None:
        provider = _resolve_probe_provider(connection.provider)
        probe = getattr(provider, "probe", None)
        if probe is not None:
            probe(
                credentials=credentials,
                timeout_seconds=settings.INTEGRATIONS_DEFAULT_TIMEOUT_SECONDS,
            )

    error: IntegrationError | None = None
    try:
        _execute_provider_call(connection=connection, operation=_probe)
        ok = True
    except IntegrationError as exc:
        error = exc
        ok = False

    record_event(
        action=AuditAction.INTEGRATION_CONNECTION_TESTED,
        target_type="integration_connection",
        target_id=connection.id,
        actor=actor,
        workspace=workspace,
        metadata={"provider": connection.provider, "ok": ok},
        request_id=request_id,
    )
    return {
        "ok": ok,
        "status": connection.status,
        "error_code": error.code if error else None,
    }


def _resolve_probe_provider(provider: str):
    if provider == IntegrationProvider.STRIPE:
        return get_payment_provider(provider=provider)
    if provider == IntegrationProvider.GOOGLE_CALENDAR:
        return get_calendar_provider(provider=provider)
    if provider == IntegrationProvider.EMAIL:
        return get_notification_provider(provider=provider)
    return get_order_provider(provider=provider)


# ---------------------------------------------------------------------------
# Shared provider-call boundary
# ---------------------------------------------------------------------------


def effective_provider_timeout(remaining_seconds: float) -> float:
    """The two-layer timeout rule (section 74-75): the provider's own
    network timeout is always strictly less than the Phase 6 tool-execution
    deadline, so the inner I/O call normally finishes (or the SDK's own
    socket timeout fires) before the outer thread-pool timeout would."""
    margin = 0.5
    bounded = min(
        float(settings.INTEGRATIONS_DEFAULT_TIMEOUT_SECONDS),
        float(settings.INTEGRATIONS_MAX_TIMEOUT_SECONDS),
        max(remaining_seconds - margin, MIN_PROVIDER_TIMEOUT_SECONDS),
    )
    return max(bounded, MIN_PROVIDER_TIMEOUT_SECONDS)


def _require_usable_connection(*, workspace: Workspace, provider: str) -> IntegrationConnection:
    connection = resolve_connection_for_tool(workspace=workspace, provider=provider)
    if connection is None:
        raise IntegrationNotConfiguredError()
    if connection.status == IntegrationConnectionStatus.DISABLED:
        raise IntegrationDisabledError()
    if not connection.credentials_configured:
        raise IntegrationNotConfiguredError()
    return connection


def _execute_provider_call(
    *, connection: IntegrationConnection, operation: Callable[[dict[str, Any]], T]
) -> T:
    """Decrypt credentials immediately before use (section 16), run
    ``operation``, record connection health, and re-raise any
    ``IntegrationError`` unchanged. Plaintext credentials never leave this
    function's local scope."""
    try:
        credentials = (
            decrypt_credentials(connection.encrypted_credentials)
            if connection.credentials_configured
            else {}
        )
    except CredentialEncryptionError as exc:
        error = IntegrationConfigurationError()
        _record_health(connection, error=error)
        raise error from exc

    try:
        result = operation(credentials)
    except IntegrationError as exc:
        _record_health(connection, error=exc)
        raise
    finally:
        # Minimize plaintext credential lifetime (section 16).
        del credentials
    _record_health(connection, error=None)
    return result


def _record_health(connection: IntegrationConnection, *, error: IntegrationError | None) -> None:
    """Last-write-wins, single-statement health update (section 117):
    avoided read-modify-write races by updating exactly the fields this
    call determines, via ``QuerySet.update`` rather than a full
    ``save()``."""
    now = timezone.now()
    fields: dict[str, Any] = {"last_checked_at": now}

    if error is None:
        fields["last_success_at"] = now
        fields["last_error_code"] = ""
        if connection.status in (
            IntegrationConnectionStatus.DEGRADED,
            IntegrationConnectionStatus.INVALID_CREDENTIALS,
        ):
            fields["status"] = IntegrationConnectionStatus.ACTIVE
    else:
        fields["last_error_code"] = error.code
        if connection.status != IntegrationConnectionStatus.DISABLED:
            if isinstance(
                error, (IntegrationAuthenticationFailedError, IntegrationPermissionDeniedError)
            ):
                # Authentication failure is distinct from a transient outage
                # (section 116) — only this class of error marks credentials
                # invalid rather than merely degraded.
                fields["status"] = IntegrationConnectionStatus.INVALID_CREDENTIALS
            elif isinstance(
                error,
                (
                    IntegrationTimeoutError,
                    IntegrationTemporarilyUnavailableError,
                    IntegrationRateLimitedError,
                ),
            ):
                fields["status"] = IntegrationConnectionStatus.DEGRADED

    IntegrationConnection.objects.filter(pk=connection.pk).update(**fields)
    for key, value in fields.items():
        setattr(connection, key, value)


# ---------------------------------------------------------------------------
# Business operations (called only from integrations.tools handlers)
# ---------------------------------------------------------------------------


def get_payment(
    *, workspace: Workspace, remaining_seconds: float, payment_reference: str, payment_provider=None
) -> NormalizedPayment:
    connection = _require_usable_connection(
        workspace=workspace, provider=IntegrationProvider.STRIPE
    )
    timeout = effective_provider_timeout(remaining_seconds)
    provider = payment_provider or get_payment_provider(provider=connection.provider)
    return _execute_provider_call(
        connection=connection,
        operation=lambda credentials: provider.get_payment(
            credentials=credentials, payment_reference=payment_reference, timeout_seconds=timeout
        ),
    )


def refund_payment(
    *,
    workspace: Workspace,
    remaining_seconds: float,
    payment_reference: str,
    amount_minor: int,
    currency: str,
    reason: str,
    idempotency_key: str,
    payment_provider=None,
) -> NormalizedRefund:
    connection = _require_usable_connection(
        workspace=workspace, provider=IntegrationProvider.STRIPE
    )
    timeout = effective_provider_timeout(remaining_seconds)
    provider = payment_provider or get_payment_provider(provider=connection.provider)
    return _execute_provider_call(
        connection=connection,
        operation=lambda credentials: provider.refund_payment(
            credentials=credentials,
            payment_reference=payment_reference,
            amount_minor=amount_minor,
            currency=currency,
            reason=reason,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout,
        ),
    )


def get_availability(
    *,
    workspace: Workspace,
    remaining_seconds: float,
    window_start,
    window_end,
    calendar_provider=None,
):
    connection = _require_usable_connection(
        workspace=workspace, provider=IntegrationProvider.GOOGLE_CALENDAR
    )
    timeout = effective_provider_timeout(remaining_seconds)
    provider = calendar_provider or get_calendar_provider(provider=connection.provider)
    return _execute_provider_call(
        connection=connection,
        operation=lambda credentials: provider.get_availability(
            credentials=credentials,
            configuration=connection.configuration,
            window_start=window_start,
            window_end=window_end,
            timeout_seconds=timeout,
        ),
    )


def create_booking(
    *,
    workspace: Workspace,
    remaining_seconds: float,
    start,
    end,
    title: str,
    attendee_email: str | None,
    idempotency_key: str,
    calendar_provider=None,
) -> NormalizedBooking:
    connection = _require_usable_connection(
        workspace=workspace, provider=IntegrationProvider.GOOGLE_CALENDAR
    )
    timeout = effective_provider_timeout(remaining_seconds)
    provider = calendar_provider or get_calendar_provider(provider=connection.provider)
    return _execute_provider_call(
        connection=connection,
        operation=lambda credentials: provider.create_booking(
            credentials=credentials,
            configuration=connection.configuration,
            start=start,
            end=end,
            title=title,
            attendee_email=attendee_email,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout,
        ),
    )


def ensure_notification_provider_configured(*, workspace: Workspace) -> None:
    """Synchronous configuration check only (Phase 10 Block 2, section 8):
    ``notification.send`` still validates a usable EMAIL connection exists
    before accepting the request — the same ``integration_not_configured`` /
    ``integration_disabled`` outcomes as before — but no longer performs the
    provider call itself; that happens later, asynchronously, once a worker
    claims the durable delivery (``notifications.notification_delivery``)."""
    _require_usable_connection(workspace=workspace, provider=IntegrationProvider.EMAIL)


def send_notification(
    *,
    workspace: Workspace,
    remaining_seconds: float,
    recipient_email: str,
    subject: str,
    body: str,
    idempotency_key: str,
    notification_provider=None,
) -> NormalizedNotification:
    connection = _require_usable_connection(workspace=workspace, provider=IntegrationProvider.EMAIL)
    timeout = effective_provider_timeout(remaining_seconds)
    provider = notification_provider or get_notification_provider(provider=connection.provider)
    return _execute_provider_call(
        connection=connection,
        operation=lambda credentials: provider.send(
            credentials=credentials,
            configuration=connection.configuration,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout,
        ),
    )


def get_order(
    *, workspace: Workspace, remaining_seconds: float, order_reference: str, order_provider=None
) -> NormalizedOrder:
    connection = _require_usable_connection(
        workspace=workspace, provider=IntegrationProvider.DEMO_COMMERCE
    )
    timeout = effective_provider_timeout(remaining_seconds)
    provider = order_provider or get_order_provider(provider=connection.provider)
    return _execute_provider_call(
        connection=connection,
        operation=lambda credentials: provider.get_order(
            credentials=credentials,
            configuration=connection.configuration,
            order_reference=order_reference,
            timeout_seconds=timeout,
        ),
    )


def get_shipment(
    *, workspace: Workspace, remaining_seconds: float, shipment_reference: str, order_provider=None
) -> NormalizedShipment:
    connection = _require_usable_connection(
        workspace=workspace, provider=IntegrationProvider.DEMO_COMMERCE
    )
    timeout = effective_provider_timeout(remaining_seconds)
    provider = order_provider or get_order_provider(provider=connection.provider)
    return _execute_provider_call(
        connection=connection,
        operation=lambda credentials: provider.get_shipment(
            credentials=credentials,
            configuration=connection.configuration,
            shipment_reference=shipment_reference,
            timeout_seconds=timeout,
        ),
    )
