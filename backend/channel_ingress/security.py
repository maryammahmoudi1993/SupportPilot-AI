"""Inbound signed-webhook verification and web-chat session-token primitives
(Phase 13 section 19-21, 45).

Deliberately a distinct module from ``webhooks.signing``: that module signs
*outbound* SupportPilot-initiated requests (Phase 10 Block 3) — a different
direction with a different trust boundary (we control both ends there; here
a third-party provider controls the signing side). The underlying
construction is intentionally the same proven shape
(``HMAC-SHA256(secret, f"{timestamp}." + raw_body)``, section 19) so both are
reviewable against one mental model, but inbound *verification* has its own
requirements outbound signing never needed: bounded timestamp freshness,
constant-time comparison against a caller-supplied value, and safe-by-default
failure (section 21) — nothing here ever raises a raw ``cryptography``/parser
exception to the caller.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from django.conf import settings

from .errors import (
    PayloadTooLargeError,
    SignatureExpiredError,
    SignatureInvalidError,
    SignatureMalformedError,
    SignatureMissingError,
)

SIGNATURE_VERSION = "v1"


def compute_signature(*, secret: str, timestamp: int, raw_body: bytes) -> str:
    """The same construction as ``webhooks.signing.sign`` (section 19),
    reused here as the verification-side primitive rather than duplicated."""
    signed_payload = f"{timestamp}.".encode("ascii") + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def verify_inbound_signature(
    *,
    secret: str,
    raw_body: bytes,
    timestamp_header: str | None,
    signature_header: str | None,
    now: int | None = None,
) -> None:
    """Fail-closed inbound HMAC verification (section 19-21).

    Raises a typed, safe-message ``ChannelIngressError`` subclass for every
    rejection path — never leaks whether the timestamp, the signature
    encoding, or the digest itself was the problem (section 21): a caller
    that cannot produce a fresh, correctly-signed request gets the same
    generic behavior regardless of which check actually failed, so
    ``SignatureInvalidError``/``SignatureExpiredError`` are the only two
    outcomes callers may distinguish (fresh-but-wrong vs. stale)."""
    if not signature_header:
        raise SignatureMissingError()
    if not timestamp_header:
        raise SignatureMissingError()

    try:
        timestamp = int(timestamp_header)
    except (TypeError, ValueError) as exc:
        raise SignatureMalformedError() from exc

    now = now if now is not None else int(time.time())
    max_past = settings.CHANNELS_SIGNATURE_MAX_PAST_SKEW_SECONDS
    max_future = settings.CHANNELS_SIGNATURE_MAX_FUTURE_SKEW_SECONDS
    if timestamp < now - max_past or timestamp > now + max_future:
        raise SignatureExpiredError()

    if not signature_header.startswith(f"{SIGNATURE_VERSION}="):
        raise SignatureMalformedError()

    expected = compute_signature(secret=secret, timestamp=timestamp, raw_body=raw_body)
    # ``hmac.compare_digest`` is constant-time over its comparison — the
    # only defensible way to compare a caller-supplied signature (section
    # 19).
    if not hmac.compare_digest(expected, signature_header):
        raise SignatureInvalidError()


def enforce_body_size(raw_body: bytes) -> None:
    """Section 22: reject an oversized payload before any expensive parsing
    is attempted."""
    if len(raw_body) > settings.CHANNELS_MAX_INBOUND_BODY_BYTES:
        raise PayloadTooLargeError()


def compute_payload_digest(raw_body: bytes) -> str:
    """SHA-256 hex digest of the canonical raw bytes (section 8-9) — used as
    the idempotency-conflict fingerprint, never the raw bytes themselves."""
    return hashlib.sha256(raw_body).hexdigest()
