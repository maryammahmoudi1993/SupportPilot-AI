"""Canonical serialization + HMAC signing (Phase 10 Block 3, section 15-18)."""

from __future__ import annotations

from webhooks.signing import build_signed_request, canonical_body, generate_signing_secret, sign

ENVELOPE = {
    "id": "evt_1",
    "type": "approval.requested",
    "version": 1,
    "created_at": "2024-01-01T00:00:00+00:00",
    "workspace_id": "ws_1",
    "data": {"summary": "x"},
}


def test_signature_deterministic_for_same_inputs():
    a = sign(secret="s1", timestamp=1000, raw_body=b'{"a":1}')
    b = sign(secret="s1", timestamp=1000, raw_body=b'{"a":1}')
    assert a == b


def test_signature_differs_on_one_byte_body_change():
    a = sign(secret="s1", timestamp=1000, raw_body=b'{"a":1}')
    b = sign(secret="s1", timestamp=1000, raw_body=b'{"a":2}')
    assert a != b


def test_signature_differs_on_different_secret():
    a = sign(secret="s1", timestamp=1000, raw_body=b'{"a":1}')
    b = sign(secret="s2", timestamp=1000, raw_body=b'{"a":1}')
    assert a != b


def test_signature_differs_on_different_timestamp():
    a = sign(secret="s1", timestamp=1000, raw_body=b'{"a":1}')
    b = sign(secret="s1", timestamp=1001, raw_body=b'{"a":1}')
    assert a != b


def test_signature_has_stable_version_prefix():
    sig = sign(secret="s1", timestamp=1000, raw_body=b"{}")
    assert sig.startswith("v1=")
    assert len(sig) == len("v1=") + 64  # hex-encoded SHA-256 digest


def test_canonical_body_is_deterministic_key_order():
    a = canonical_body({"b": 1, "a": 2})
    b = canonical_body({"a": 2, "b": 1})
    assert a == b


def test_build_signed_request_signs_exact_bytes_sent():
    """Section 16-17 byte-level requirement: the bytes returned as
    ``raw_body`` are the exact bytes the signature was computed over — no
    second serialization anywhere in between."""
    signed = build_signed_request(
        secret="s1", envelope=ENVELOPE, event_id="evt_1", delivery_id="dlv_1", now=1000
    )
    expected_signature = sign(secret="s1", timestamp=1000, raw_body=signed.raw_body)
    assert signed.signature == expected_signature
    assert signed.raw_body == canonical_body(ENVELOPE)


def test_build_signed_request_headers_contain_stable_identity():
    signed = build_signed_request(
        secret="s1", envelope=ENVELOPE, event_id="evt_1", delivery_id="dlv_1", now=1000
    )
    assert signed.headers["X-SupportPilot-Event-Id"] == "evt_1"
    assert signed.headers["X-SupportPilot-Delivery-Id"] == "dlv_1"
    assert signed.headers["X-SupportPilot-Timestamp"] == "1000"
    assert signed.headers["X-SupportPilot-Signature"] == signed.signature
    assert signed.headers["Idempotency-Key"] == "dlv_1"
    assert signed.headers["Content-Type"] == "application/json"
    assert signed.headers["User-Agent"].startswith("SupportPilot-Webhook/")


def test_generate_signing_secret_is_long_and_random():
    a = generate_signing_secret()
    b = generate_signing_secret()
    assert a != b
    assert len(a) == 64
    int(a, 16)  # must be valid hex
