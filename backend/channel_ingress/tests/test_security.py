"""Real cryptographic inbound signature verification (Phase 13 section 57).
No mocked ``True``/``False`` verifier — every case exercises the actual
HMAC-SHA256 construction."""

from __future__ import annotations

import json
import time

import pytest

from channel_ingress.errors import (
    SignatureExpiredError,
    SignatureInvalidError,
    SignatureMalformedError,
    SignatureMissingError,
)
from channel_ingress.security import compute_signature, enforce_body_size, verify_inbound_signature

SECRET = "correct-secret"
BODY = json.dumps({"event_id": "evt-1", "body": "hi"}).encode("utf-8")


def _headers(*, secret=SECRET, ts=None, body=BODY):
    ts = ts if ts is not None else int(time.time())
    return {
        "X-SupportPilot-Timestamp": str(ts),
        "X-SupportPilot-Signature": compute_signature(secret=secret, timestamp=ts, raw_body=body),
    }


def test_valid_signature_is_accepted():
    headers = _headers()
    verify_inbound_signature(
        secret=SECRET,
        raw_body=BODY,
        timestamp_header=headers["X-SupportPilot-Timestamp"],
        signature_header=headers["X-SupportPilot-Signature"],
    )


def test_wrong_signature_is_rejected():
    headers = _headers()
    with pytest.raises(SignatureInvalidError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header="v1=" + "0" * 64,
        )


def test_wrong_secret_is_rejected():
    headers = _headers(secret="a-different-secret")
    with pytest.raises(SignatureInvalidError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header=headers["X-SupportPilot-Signature"],
        )


def test_expired_timestamp_is_rejected():
    headers = _headers(ts=int(time.time()) - 10_000)
    with pytest.raises(SignatureExpiredError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header=headers["X-SupportPilot-Signature"],
        )


def test_future_timestamp_beyond_tolerance_is_rejected():
    headers = _headers(ts=int(time.time()) + 10_000)
    with pytest.raises(SignatureExpiredError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header=headers["X-SupportPilot-Signature"],
        )


def test_missing_timestamp_is_rejected():
    headers = _headers()
    with pytest.raises(SignatureMissingError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header=None,
            signature_header=headers["X-SupportPilot-Signature"],
        )


def test_missing_signature_is_rejected():
    headers = _headers()
    with pytest.raises(SignatureMissingError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header=None,
        )


def test_malformed_signature_encoding_is_rejected():
    headers = _headers()
    with pytest.raises(SignatureMalformedError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header="not-a-real-signature",
        )


def test_malformed_timestamp_is_rejected():
    headers = _headers()
    with pytest.raises(SignatureMalformedError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header="not-a-number",
            signature_header=headers["X-SupportPilot-Signature"],
        )


def test_payload_modified_after_signing_is_rejected():
    headers = _headers(body=BODY)
    tampered_body = BODY + b"tampered"
    with pytest.raises(SignatureInvalidError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=tampered_body,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header=headers["X-SupportPilot-Signature"],
        )


def test_same_valid_event_replayed_verifies_both_times():
    """Signature freshness alone never rejects a genuine replay within the
    tolerance window (section 20) — provider-event dedup, tested
    separately in ``test_ingest_dedup.py``, is what actually prevents a
    duplicate logical event, not signature verification."""
    headers = _headers()
    for _ in range(2):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=BODY,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header=headers["X-SupportPilot-Signature"],
        )


def test_different_event_with_reused_signature_is_rejected():
    headers = _headers(body=BODY)
    other_body = json.dumps({"event_id": "evt-2", "body": "different"}).encode("utf-8")
    with pytest.raises(SignatureInvalidError):
        verify_inbound_signature(
            secret=SECRET,
            raw_body=other_body,
            timestamp_header=headers["X-SupportPilot-Timestamp"],
            signature_header=headers["X-SupportPilot-Signature"],
        )


def test_oversized_body_is_rejected(settings):
    settings.CHANNELS_MAX_INBOUND_BODY_BYTES = 10
    from channel_ingress.errors import PayloadTooLargeError

    with pytest.raises(PayloadTooLargeError):
        enforce_body_size(b"x" * 11)


def test_body_at_the_limit_is_accepted(settings):
    settings.CHANNELS_MAX_INBOUND_BODY_BYTES = 10
    enforce_body_size(b"x" * 10)
