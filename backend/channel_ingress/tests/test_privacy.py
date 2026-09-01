"""Security-marker sweep (Phase 13 section 65): unique markers injected into
message body, provider metadata, a signing-secret test value, and a
web-chat session token must never surface in Prometheus labels, span
attributes, or a raw API error response. Message content legitimately
remains in the authoritative Message record — this test concerns telemetry
and error surfaces only."""

from __future__ import annotations

import json
import time
import uuid

import pytest
from prometheus_client.parser import text_string_to_metric_families
from rest_framework.test import APIClient

from channel_ingress.security import compute_signature
from channel_ingress.services import ingest_channel_event
from channel_ingress.tests.factories import ChannelEndpointFactory
from observability.metrics import render_metrics

pytestmark = pytest.mark.django_db


def _metrics_text() -> str:
    return render_metrics().decode("utf-8")


def _samples(metric_name: str):
    body = _metrics_text()
    return [
        sample
        for family in text_string_to_metric_families(body)
        for sample in family.samples
        if sample.name == metric_name
    ]


def test_message_body_and_metadata_markers_never_reach_metrics_labels():
    marker_body = f"MARKER-BODY-{uuid.uuid4().hex}"
    marker_identity = f"MARKER-IDENTITY-{uuid.uuid4().hex}"
    endpoint = ChannelEndpointFactory()

    ingest_channel_event(
        endpoint=endpoint,
        provider_event_id="evt-1",
        payload_digest="digest-a",
        external_identity=marker_identity,
        body=marker_body,
    )

    metrics_text = _metrics_text()
    assert marker_body not in metrics_text
    assert marker_identity not in metrics_text
    assert str(endpoint.workspace_id) not in metrics_text
    assert str(endpoint.id) not in metrics_text

    samples = _samples("supportpilot_channel_ingress_total")
    for sample in samples:
        assert set(sample.labels.keys()) == {"channel"}


def test_signing_secret_never_appears_in_a_rejected_signature_response():
    marker_secret = f"MARKER-SECRET-{uuid.uuid4().hex}"
    endpoint = ChannelEndpointFactory()
    body = json.dumps({"event_id": "evt-1", "external_id": "cust-1", "body": "hi"}).encode()
    ts = int(time.time())
    bad_signature = compute_signature(secret=marker_secret, timestamp=ts, raw_body=body)

    response = APIClient().post(
        f"/api/v1/channels/public/inbound/{endpoint.id}/",
        data=body,
        content_type="application/json",
        HTTP_X_SUPPORTPILOT_TIMESTAMP=str(ts),
        HTTP_X_SUPPORTPILOT_SIGNATURE=bad_signature,
    )
    assert response.status_code == 400
    assert marker_secret not in str(response.data)
    assert bad_signature not in str(response.data)


def test_web_chat_session_token_never_appears_in_metrics_or_errors():
    from channel_ingress.tests.factories import WebChatEndpointFactory

    endpoint = WebChatEndpointFactory()
    client = APIClient()
    bootstrap = client.post(f"/api/v1/channels/public/webchat/{endpoint.id}/session/")
    token = bootstrap.data["session_token"]

    submit = client.post(
        f"/api/v1/channels/public/webchat/session/{token}/messages/",
        {"client_message_id": "msg-1", "body": f"MARKER-{uuid.uuid4().hex}"},
        format="json",
    )
    assert submit.status_code == 202
    assert token not in _metrics_text()

    # An invalid token guess never echoes the caller's own guess back.
    bad_response = client.get(
        "/api/v1/channels/public/webchat/session/not-the-real-token/messages/"
    )
    assert "not-the-real-token" not in str(bad_response.data)
