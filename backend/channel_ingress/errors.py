"""Bounded, stable ingress failure taxonomy (Phase 13 section 50).

Every failure this app can produce — signature verification, payload
parsing, dedup/idempotency, identity resolution, orchestration handoff,
response routing — maps to exactly one of the codes below. Never a raw
exception class/message: those are untrusted (may carry provider- or
credential-adjacent text) and unstable (a library upgrade can silently
change them), so nothing here ever persists or returns one directly.
"""

from __future__ import annotations


class ChannelIngressError(Exception):
    """Base class for every typed, safe-message error this app raises.
    ``code`` is the stable taxonomy value (section 50); ``safe_message`` is
    the only text ever shown to a caller or persisted to a failure field."""

    code = "processing_failed"
    safe_message = "The request could not be processed."


class SignatureMissingError(ChannelIngressError):
    code = "signature_invalid"
    safe_message = "The request signature is missing or invalid."


class SignatureMalformedError(ChannelIngressError):
    code = "signature_invalid"
    safe_message = "The request signature is missing or invalid."


class SignatureInvalidError(ChannelIngressError):
    code = "signature_invalid"
    safe_message = "The request signature is missing or invalid."


class SignatureExpiredError(ChannelIngressError):
    code = "signature_expired"
    safe_message = "The request signature has expired."


class PayloadInvalidError(ChannelIngressError):
    code = "payload_invalid"
    safe_message = "The request payload is malformed."


class PayloadTooLargeError(ChannelIngressError):
    code = "payload_too_large"
    safe_message = "The request payload exceeds the allowed size."


class IdempotencyConflictError(ChannelIngressError):
    code = "idempotency_conflict"
    safe_message = "This event id was already used with different content."


class IdentityNotFoundError(ChannelIngressError):
    code = "identity_not_found"
    safe_message = "No matching customer identity was found."


class IdentityAmbiguousError(ChannelIngressError):
    code = "identity_ambiguous"
    safe_message = "The inbound identity matched more than one customer record."


class EndpointDisabledError(ChannelIngressError):
    code = "endpoint_disabled"
    safe_message = "This channel endpoint is not currently active."


class UnsupportedEventError(ChannelIngressError):
    code = "unsupported_event"
    safe_message = "This event type is not supported on this channel."


class SessionInvalidError(ChannelIngressError):
    code = "session_invalid"
    safe_message = "The chat session is invalid or has expired."


class OrchestrationFailedError(ChannelIngressError):
    code = "orchestration_failed"
    safe_message = "The message was received but could not be processed."


class ResponseRouteFailedError(ChannelIngressError):
    code = "response_route_failed"
    safe_message = "The response could not be routed to its destination channel."
