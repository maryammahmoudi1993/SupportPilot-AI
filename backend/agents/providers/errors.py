"""Normalized, safe provider/application error taxonomy.

Every provider adapter (fake or real) must raise one of these instead of
letting a vendor SDK exception escape. ``safe_message`` is what may reach an
API response or a log line; the original exception, headers, and any secret
material must never be exposed beyond the adapter boundary.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for every normalized provider failure."""

    code = "provider_unknown_error"
    safe_message = "The AI provider returned an unexpected error."
    retryable = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.safe_message)


class ProviderAuthenticationError(ProviderError):
    code = "provider_authentication_failed"
    safe_message = "The AI provider rejected the configured credentials."
    retryable = False


class ProviderRateLimitedError(ProviderError):
    code = "provider_rate_limited"
    safe_message = "The AI provider is rate-limiting requests."
    retryable = True


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    safe_message = "The AI provider did not respond in time."
    retryable = True


class ProviderTemporarilyUnavailableError(ProviderError):
    code = "provider_temporarily_unavailable"
    safe_message = "The AI provider is temporarily unavailable."
    retryable = True


class ProviderInvalidRequestError(ProviderError):
    code = "provider_invalid_request"
    safe_message = "The request to the AI provider was invalid."
    retryable = False


class ProviderMalformedResponseError(ProviderError):
    code = "provider_malformed_response"
    safe_message = "The AI provider returned a malformed response."
    retryable = False


class ProviderContentRejectedError(ProviderError):
    code = "provider_content_rejected"
    safe_message = "The AI provider rejected the content."
    retryable = False


class ProviderConfigurationError(ProviderError):
    code = "provider_configuration_error"
    safe_message = "The AI provider is not configured correctly."
    retryable = False
