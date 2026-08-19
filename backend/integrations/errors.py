"""Normalized, safe integration/provider error taxonomy (section 20-21).

Every provider adapter (fake or real) raises one of these — never a raw
vendor SDK exception, HTTP response, or traceback. ``retryable`` is
descriptive metadata for callers building a ``tools.contracts.RetryPolicy``;
it is not itself consulted by the Phase 6 execution service (section 21).

``integrations.tools`` bridges these into ``tools.errors.ToolError`` (via
``IntegrationToolError``) at the tool-handler boundary so every business
tool plugs into the *existing* Phase 6 execution/persistence/redaction path
— there is no second error-handling path (section 9, 20).
"""

from __future__ import annotations


class IntegrationError(Exception):
    """Base class for every normalized integration failure."""

    code = "integration_unknown_error"
    safe_message = "The integration request could not be completed."
    retryable = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)
        if message:
            self.safe_message = message


class IntegrationNotConfiguredError(IntegrationError):
    code = "integration_not_configured"
    safe_message = "This integration has not been configured for this workspace."


class IntegrationDisabledError(IntegrationError):
    code = "integration_disabled"
    safe_message = "This integration is currently disabled."


class IntegrationAuthenticationFailedError(IntegrationError):
    code = "integration_authentication_failed"
    safe_message = "The provider rejected the configured credentials."


class IntegrationPermissionDeniedError(IntegrationError):
    code = "integration_permission_denied"
    safe_message = "The provider denied this operation."


class IntegrationRateLimitedError(IntegrationError):
    code = "integration_rate_limited"
    safe_message = "The provider is rate-limiting requests."
    retryable = True


class IntegrationTimeoutError(IntegrationError):
    code = "integration_timeout"
    safe_message = "The provider did not respond in time."
    retryable = True


class IntegrationTemporarilyUnavailableError(IntegrationError):
    code = "integration_temporarily_unavailable"
    safe_message = "The provider is temporarily unavailable."
    retryable = True


class IntegrationInvalidRequestError(IntegrationError):
    code = "integration_invalid_request"
    safe_message = "The request to the provider was invalid."


class IntegrationNotFoundError(IntegrationError):
    code = "integration_not_found"
    safe_message = "The requested resource was not found."


class IntegrationConflictError(IntegrationError):
    code = "integration_conflict"
    safe_message = "The request conflicts with the provider's current state."


class IntegrationMalformedResponseError(IntegrationError):
    code = "integration_malformed_response"
    safe_message = "The provider returned an unexpected response."


class IntegrationConfigurationError(IntegrationError):
    code = "integration_configuration_error"
    safe_message = "This integration is misconfigured."


class IntegrationProviderNotSupportedError(IntegrationError):
    code = "integration_provider_not_supported"
    safe_message = "This provider is not supported."


# --- Business-specific normalized errors (section 20) -----------------------


class CustomerNotFoundError(IntegrationError):
    code = "customer_not_found"
    safe_message = "Customer not found."


class OrderNotFoundError(IntegrationError):
    code = "order_not_found"
    safe_message = "Order not found."


class ShipmentNotFoundError(IntegrationError):
    code = "shipment_not_found"
    safe_message = "Shipment not found."


class TicketNotFoundError(IntegrationError):
    code = "ticket_not_found"
    safe_message = "Ticket not found."


class PaymentNotFoundError(IntegrationError):
    code = "payment_not_found"
    safe_message = "Payment not found."


class RefundNotAllowedByProviderError(IntegrationError):
    code = "refund_not_allowed_by_provider"
    safe_message = "The provider will not allow this refund."


class RefundAlreadyExistsError(IntegrationError):
    code = "refund_already_exists"
    safe_message = "A refund for this payment already exists."


class CalendarSlotUnavailableError(IntegrationError):
    code = "calendar_slot_unavailable"
    safe_message = "The requested time slot is no longer available."


class BookingAlreadyExistsError(IntegrationError):
    code = "booking_already_exists"
    safe_message = "A booking for this request already exists."


#: Codes safe to classify as retryable across every read-oriented tool
#: (section 21-22). Financial/booking tools use a narrower subset — see
#: ``integrations.tools``.
RETRYABLE_INTEGRATION_CODES = frozenset(
    {
        IntegrationRateLimitedError.code,
        IntegrationTemporarilyUnavailableError.code,
        IntegrationTimeoutError.code,
    }
)
