"""Stable, safe webhook-domain error taxonomy (Phase 10 Block 3).

Every raised error here carries a fixed, stable ``code`` and ``safe_message``
— never a raw URL-parsing exception, DNS resolver exception, TLS exception,
or provider response text (section 31-32).
"""

from __future__ import annotations


class WebhookError(Exception):
    code = "webhook_error"
    safe_message = "The webhook request could not be processed."
    #: Whether a failure of this kind may be retried against the same
    #: endpoint later. Security/configuration failures are never retryable.
    retryable = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)
        if message:
            self.safe_message = message


class WebhookNotFoundError(WebhookError):
    code = "webhook_not_found"
    safe_message = "Webhook resource not found."


class WebhookInvalidURLError(WebhookError):
    """Malformed, non-http(s), or otherwise structurally rejected URL
    (section 20) — never reveals which specific parsing rule failed beyond
    a generic safe message, and never echoes the offending URL."""

    code = "webhook_invalid_url"
    safe_message = "The webhook URL is not valid."


class WebhookDestinationBlockedError(WebhookError):
    """SSRF policy rejection (section 21-24): the hostname is, or resolves
    to, a disallowed address. Deliberately generic — never confirms or
    denies which specific internal address was reached, so this response
    cannot be used to probe internal network topology."""

    code = "webhook_destination_blocked"
    safe_message = "This destination is not allowed."


class WebhookDnsResolutionError(WebhookError):
    code = "webhook_dns_resolution_failed"
    safe_message = "The webhook hostname could not be resolved."
    retryable = True


class WebhookEndpointDisabledError(WebhookError):
    code = "webhook_endpoint_disabled"
    safe_message = "This webhook endpoint is disabled."


class WebhookSigningNotConfiguredError(WebhookError):
    code = "webhook_signing_not_configured"
    safe_message = "This webhook endpoint has no signing secret configured."


class WebhookRedirectRejectedError(WebhookError):
    code = "webhook_redirect_rejected"
    safe_message = "The webhook endpoint returned a redirect, which is not followed."


class WebhookTimeoutError(WebhookError):
    code = "webhook_timeout"
    safe_message = "The webhook endpoint did not respond in time."
    retryable = True


class WebhookConnectionError(WebhookError):
    code = "webhook_connection_failed"
    safe_message = "Could not connect to the webhook endpoint."
    retryable = True


class WebhookTlsError(WebhookError):
    """Certificate/TLS validation failure — never blindly retried (section
    31): a bad or expired certificate does not fix itself between
    attempts, and treating it as retryable would just burn the attempt
    budget."""

    code = "webhook_tls_error"
    safe_message = "The webhook endpoint's TLS certificate could not be validated."


class WebhookInvalidEventTypeError(WebhookError):
    code = "webhook_invalid_event_type"
    safe_message = "One or more subscribed event types are not recognized."


class WebhookDeliveryNotRedrivableError(WebhookError):
    """Manual redrive (Phase 10 Block 4, section 35-36) only ever applies to
    a terminal, exhausted delivery (``FAILED``/``DEAD``) — never one that is
    actively claimed, already delivered, or still pending its own scheduled
    retry. Deliberately generic (never reveals the delivery's actual current
    status) — this is a safe conflict outcome, not an operational error."""

    code = "webhook_delivery_not_redrivable"
    safe_message = "This delivery cannot be redriven in its current state."


class WebhookUnexpectedTransportError(WebhookError):
    """Fail-closed classification for a transport failure this module does
    not explicitly recognize (section 15, 30) — never retried automatically."""

    code = "webhook_unexpected_transport_error"
    safe_message = "An unexpected error occurred sending the webhook."
