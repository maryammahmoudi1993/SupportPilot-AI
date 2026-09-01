"""Generic signed webhook + email-style adapter parsing/normalization
(Phase 13 section 23, 59)."""

from __future__ import annotations

import json
import time

import pytest

from channel_ingress.adapters import get_adapter
from channel_ingress.adapters.email_adapter import EmailInboundAdapter
from channel_ingress.adapters.generic_webhook import GenericSignedWebhookAdapter
from channel_ingress.errors import PayloadInvalidError, SignatureInvalidError, UnsupportedEventError
from channel_ingress.security import compute_signature
from channel_ingress.tests.factories import (
    TEST_SIGNING_SECRET,
    ChannelEndpointFactory,
    EmailEndpointFactory,
)

pytestmark = pytest.mark.django_db


def _signed_headers(body: bytes, secret: str = TEST_SIGNING_SECRET):
    ts = int(time.time())
    return {
        "X-SupportPilot-Timestamp": str(ts),
        "X-SupportPilot-Signature": compute_signature(secret=secret, timestamp=ts, raw_body=body),
    }


def test_get_adapter_resolves_generic_and_email():
    assert isinstance(get_adapter("generic_webhook"), GenericSignedWebhookAdapter)
    assert isinstance(get_adapter("email"), EmailInboundAdapter)


def test_get_adapter_rejects_web_chat():
    with pytest.raises(UnsupportedEventError):
        get_adapter("web_chat")


def test_generic_adapter_normalizes_a_valid_event():
    endpoint = ChannelEndpointFactory()
    adapter = get_adapter(endpoint.channel)
    body = json.dumps(
        {
            "event_id": "evt-1",
            "thread_id": "thread-1",
            "external_id": "cust-1",
            "subject": "hello",
            "body": "I need help",
        }
    ).encode("utf-8")
    adapter.verify_signature(endpoint=endpoint, raw_body=body, headers=_signed_headers(body))
    parsed = adapter.parse_event(raw_body=body)
    canonical = adapter.normalize(endpoint=endpoint, parsed=parsed)
    assert canonical.provider_event_id == "evt-1"
    assert canonical.external_identity == "cust-1"
    assert canonical.body == "I need help"


def test_generic_adapter_rejects_bad_signature():
    endpoint = ChannelEndpointFactory()
    adapter = get_adapter(endpoint.channel)
    body = json.dumps({"event_id": "evt-1", "external_id": "cust-1", "body": "hi"}).encode("utf-8")
    with pytest.raises(SignatureInvalidError):
        adapter.verify_signature(
            endpoint=endpoint, raw_body=body, headers=_signed_headers(body, secret="wrong-secret")
        )


def test_generic_adapter_rejects_non_json_body():
    endpoint = ChannelEndpointFactory()
    adapter = get_adapter(endpoint.channel)
    with pytest.raises(PayloadInvalidError):
        adapter.parse_event(raw_body=b"not json at all")


def test_generic_adapter_rejects_missing_required_fields():
    endpoint = ChannelEndpointFactory()
    adapter = get_adapter(endpoint.channel)
    body = json.dumps({"event_id": "evt-1"}).encode("utf-8")
    with pytest.raises(PayloadInvalidError):
        adapter.parse_event(raw_body=body)


def test_generic_adapter_rejects_a_json_array_body():
    """Section 22-23: bounded, non-recursive parsing only — a
    structurally-valid-JSON-but-wrong-shape body is rejected, not coerced."""
    endpoint = ChannelEndpointFactory()
    adapter = get_adapter(endpoint.channel)
    with pytest.raises(PayloadInvalidError):
        adapter.parse_event(raw_body=b"[1, 2, 3]")


def test_email_adapter_normalizes_sender_to_lowercase():
    endpoint = EmailEndpointFactory()
    adapter = get_adapter(endpoint.channel)
    body = json.dumps({"event_id": "evt-1", "from": "Jane.Doe@Example.COM", "body": "hi"}).encode(
        "utf-8"
    )
    parsed = adapter.parse_event(raw_body=body)
    canonical = adapter.normalize(endpoint=endpoint, parsed=parsed)
    assert canonical.external_identity == "jane.doe@example.com"


def test_email_adapter_rejects_malformed_sender():
    endpoint = EmailEndpointFactory()
    adapter = get_adapter(endpoint.channel)
    body = json.dumps({"event_id": "evt-1", "from": "not-an-email", "body": "hi"}).encode("utf-8")
    with pytest.raises(PayloadInvalidError):
        parsed = adapter.parse_event(raw_body=body)
        adapter.normalize(endpoint=endpoint, parsed=parsed)


def test_email_adapter_never_trusts_html_as_the_body():
    """Section 23: HTML, if present, is untrusted content — never
    normalized as the trusted plain-text body."""
    endpoint = EmailEndpointFactory()
    adapter = get_adapter(endpoint.channel)
    body = json.dumps(
        {
            "event_id": "evt-1",
            "from": "jane@example.com",
            "body": "plain text body",
            "body_html": "<script>alert(1)</script>",
        }
    ).encode("utf-8")
    parsed = adapter.parse_event(raw_body=body)
    canonical = adapter.normalize(endpoint=endpoint, parsed=parsed)
    assert canonical.body == "plain text body"
    assert "<script>" not in canonical.body
    assert canonical.metadata["had_html_body"] == "true"


def test_unsupported_channel_type_is_rejected():
    with pytest.raises(UnsupportedEventError):
        get_adapter("nonexistent_channel_type")
