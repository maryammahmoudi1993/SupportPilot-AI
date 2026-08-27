"""Canonical serialization + HMAC request signing (Phase 10 Block 3, section
15-18).

``build_signed_request`` is the single place the event body is ever
serialized: the exact bytes returned as ``raw_body`` are the exact bytes the
signature covers and the exact bytes the transport sends — never serialized
twice (section 16).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

SIGNATURE_VERSION = "v1"
USER_AGENT = "SupportPilot-Webhook/1"


@dataclass(frozen=True)
class SignedRequest:
    raw_body: bytes
    headers: dict[str, str]
    timestamp: int
    signature: str


def canonical_body(envelope: dict[str, Any]) -> bytes:
    """Serialize an event envelope exactly once, deterministically (stable
    key order) so the same logical event always produces the same bytes."""
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign(*, secret: str, timestamp: int, raw_body: bytes) -> str:
    """HMAC-SHA256 over ``b"<timestamp>." + raw_body`` (section 15) — the
    timestamp is bound into the signature so a captured signature cannot be
    replayed against a different body, and a receiver can reject stale
    timestamps independently of signature validity."""
    signed_payload = f"{timestamp}.".encode("ascii") + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def build_signed_request(
    *,
    secret: str,
    envelope: dict[str, Any],
    event_id: str,
    delivery_id: str,
    now: int | None = None,
) -> SignedRequest:
    """Build the exact bytes to send plus their signature headers. Callers
    must pass ``raw_body`` (never re-derive it from ``envelope``) straight
    into the transport (section 16)."""
    timestamp = now if now is not None else int(time.time())
    raw_body = canonical_body(envelope)
    signature = sign(secret=secret, timestamp=timestamp, raw_body=raw_body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-SupportPilot-Event-Id": event_id,
        "X-SupportPilot-Delivery-Id": delivery_id,
        "X-SupportPilot-Timestamp": str(timestamp),
        "X-SupportPilot-Signature": signature,
        # The same value on every attempt for this delivery (section 18) —
        # a receiver capable of dedup can use it exactly like the stable
        # provider idempotency key Block 2 already established.
        "Idempotency-Key": delivery_id,
    }
    return SignedRequest(
        raw_body=raw_body, headers=headers, timestamp=timestamp, signature=signature
    )


def generate_signing_secret() -> str:
    """Server-generated, cryptographically secure signing secret (section
    13) — never client-suppliable. 64 hex characters (256 bits) from
    ``secrets``, the standard library's CSPRNG-backed module for exactly
    this purpose."""
    return secrets.token_hex(32)
