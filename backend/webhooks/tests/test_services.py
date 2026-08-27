"""Webhook endpoint management, event fanout, and delivery-handler tests
(Phase 10 Block 3, section 10-11, 14, 34-35, 56-66)."""

from __future__ import annotations

import json
import logging

import pytest

from audit.models import AuditAction, AuditEvent
from integrations.crypto import decrypt_credentials
from notifications.errors import DeliveryNotClaimableError
from notifications.models import AttemptStatus, DeliveryAttempt, DeliveryChannel, DeliveryStatus
from notifications.services import claim_delivery, create_delivery
from webhooks.errors import (
    WebhookDestinationBlockedError,
    WebhookEndpointDisabledError,
    WebhookInvalidEventTypeError,
    WebhookInvalidURLError,
    WebhookTimeoutError,
)
from webhooks.models import WebhookDelivery, WebhookEndpointStatus, WebhookEventType
from webhooks.services import (
    UNEXPECTED_ERROR_CODE,
    build_event_envelope,
    create_endpoint,
    emit_event,
    handle_webhook_delivery_attempt,
    rotate_secret,
    set_endpoint_status,
    update_endpoint,
)
from webhooks.signing import sign
from webhooks.tests.factories import TEST_SECRET, WebhookEndpointFactory, WebhookEventFactory
from webhooks.transport import TransportResult
from workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def _fake_transport(status=204, raise_exc=None):
    calls: list[dict] = []

    def fake(*, scheme, ip, port, hostname, path_and_query, headers, body, method="POST"):
        calls.append(
            {
                "scheme": scheme,
                "ip": ip,
                "port": port,
                "hostname": hostname,
                "path_and_query": path_and_query,
                "headers": headers,
                "body": body,
            }
        )
        if raise_exc is not None:
            raise raise_exc

        return TransportResult(status_code=status, latency_ms=1)

    return fake, calls


# ---------------------------------------------------------------------------
# Endpoint CRUD (section 12-14, 37-39)
# ---------------------------------------------------------------------------


def test_create_endpoint_returns_secret_once_and_encrypts_at_rest(monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    workspace = WorkspaceFactory()
    endpoint, secret = create_endpoint(
        workspace=workspace,
        actor=None,
        name="My endpoint",
        url="https://example.com/hook",
        subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED],
    )
    assert len(secret) == 64
    assert endpoint.encrypted_signing_secret != secret
    assert decrypt_credentials(endpoint.encrypted_signing_secret) == {"secret": secret}
    assert AuditEvent.objects.filter(
        action=AuditAction.WEBHOOK_ENDPOINT_CREATED, target_id=str(endpoint.id)
    ).exists()


def test_create_endpoint_rejects_invalid_url():
    with pytest.raises(WebhookInvalidURLError):
        create_endpoint(
            workspace=WorkspaceFactory(),
            actor=None,
            name="x",
            url="ftp://example.com",
            subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED],
        )


def test_create_endpoint_rejects_ssrf_destination():
    with pytest.raises(WebhookDestinationBlockedError):
        create_endpoint(
            workspace=WorkspaceFactory(),
            actor=None,
            name="x",
            url="https://127.0.0.1/hook",
            subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED],
        )


@pytest.mark.parametrize(
    "event_types",
    [
        [],
        ["not.a.real.event"],
        [WebhookEventType.APPROVAL_REQUESTED, WebhookEventType.APPROVAL_REQUESTED],
    ],
)
def test_create_endpoint_rejects_invalid_event_types(event_types, monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    with pytest.raises(WebhookInvalidEventTypeError):
        create_endpoint(
            workspace=WorkspaceFactory(),
            actor=None,
            name="x",
            url="https://example.com/hook",
            subscribed_event_types=event_types,
        )


def test_update_endpoint_changes_only_provided_fields(monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    endpoint = WebhookEndpointFactory(name="Old name")
    updated = update_endpoint(
        workspace=endpoint.workspace, endpoint=endpoint, actor=None, name="New name"
    )
    assert updated.name == "New name"
    assert updated.url == endpoint.url


def test_set_endpoint_status_disabled_audits_disabled_action():
    endpoint = WebhookEndpointFactory()
    updated = set_endpoint_status(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        actor=None,
        status=WebhookEndpointStatus.DISABLED,
    )
    assert updated.status == WebhookEndpointStatus.DISABLED
    assert AuditEvent.objects.filter(
        action=AuditAction.WEBHOOK_ENDPOINT_DISABLED, target_id=str(endpoint.id)
    ).exists()


def test_rotate_secret_returns_new_secret_and_invalidates_old(monkeypatch):
    endpoint = WebhookEndpointFactory()
    original_encrypted = endpoint.encrypted_signing_secret
    updated, new_secret = rotate_secret(workspace=endpoint.workspace, endpoint=endpoint, actor=None)
    assert updated.encrypted_signing_secret != original_encrypted
    assert decrypt_credentials(updated.encrypted_signing_secret) == {"secret": new_secret}
    assert new_secret != TEST_SECRET
    assert AuditEvent.objects.filter(
        action=AuditAction.WEBHOOK_SECRET_ROTATED, target_id=str(endpoint.id)
    ).exists()


# ---------------------------------------------------------------------------
# Event envelope + fanout (section 7-11)
# ---------------------------------------------------------------------------


def test_build_event_envelope_shape():
    event = WebhookEventFactory(payload_snapshot={"foo": "bar"})
    envelope = build_event_envelope(event)
    assert envelope == {
        "id": str(event.id),
        "type": event.event_type,
        "version": event.version,
        "created_at": event.created_at.isoformat(),
        "workspace_id": str(event.workspace_id),
        "data": {"foo": "bar"},
    }


def test_emit_event_fans_out_to_subscribed_active_endpoints_only():
    workspace = WorkspaceFactory()
    subscribed_active = WebhookEndpointFactory(
        workspace=workspace, subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED]
    )
    WebhookEndpointFactory(
        workspace=workspace,
        subscribed_event_types=[WebhookEventType.APPROVAL_APPROVED],  # not subscribed
    )
    WebhookEndpointFactory(
        workspace=workspace,
        status=WebhookEndpointStatus.DISABLED,
        subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED],  # disabled
    )
    other_workspace_endpoint = WebhookEndpointFactory(
        subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED]
    )  # different workspace

    event = emit_event(
        workspace=workspace, event_type=WebhookEventType.APPROVAL_REQUESTED, data={"x": 1}
    )

    deliveries = WebhookDelivery.objects.filter(event=event)
    assert deliveries.count() == 1
    assert deliveries.first().endpoint_id == subscribed_active.id
    assert not WebhookDelivery.objects.filter(endpoint=other_workspace_endpoint).exists()


def test_emit_event_creates_one_delivery_per_endpoint_event_pair_never_duplicated():
    endpoint = WebhookEndpointFactory()
    event = emit_event(
        workspace=endpoint.workspace, event_type=WebhookEventType.APPROVAL_REQUESTED, data={}
    )
    assert WebhookDelivery.objects.filter(endpoint=endpoint, event=event).count() == 1


def test_emit_event_rejects_unknown_event_type():
    with pytest.raises(WebhookInvalidEventTypeError):
        emit_event(workspace=WorkspaceFactory(), event_type="not.a.real.event", data={})


# ---------------------------------------------------------------------------
# Handler: success / failure classification (section 56-60)
# ---------------------------------------------------------------------------


def _delivery_for(endpoint, event, monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    return delivery


def test_success_delivers_signed_body_and_marks_delivered(monkeypatch):
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)
    fake_transport, calls = _fake_transport(status=204)
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.attempt_count == 1
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.status == AttemptStatus.SUCCEEDED
    assert attempt.response_status_code == 204

    assert len(calls) == 1
    sent = calls[0]
    assert sent["headers"]["X-SupportPilot-Delivery-Id"] == str(delivery.id)
    assert sent["headers"]["X-SupportPilot-Event-Id"] == str(event.id)
    assert "X-SupportPilot-Signature" in sent["headers"]

    assert json.loads(sent["body"])["type"] == event.event_type


@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
def test_retryable_http_status_schedules_retry(monkeypatch, status_code):
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)
    fake_transport, _calls = _fake_transport(status=status_code)
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED
    assert delivery.last_error_code == f"webhook_http_{status_code}"
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.retryable is True
    assert attempt.response_status_code == status_code


def test_terminal_http_status_marks_dead(monkeypatch):
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)
    fake_transport, _calls = _fake_transport(status=400)
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == "webhook_http_400"
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.retryable is False


def test_timeout_is_retryable_with_no_raw_exception_persisted(monkeypatch):

    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)
    fake_transport, _calls = _fake_transport(raise_exc=WebhookTimeoutError())
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED
    assert delivery.last_error_code == "webhook_timeout"
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert attempt.retryable is True
    assert "urllib3" not in attempt.safe_error_code
    assert "Traceback" not in attempt.safe_error_code


def test_max_attempts_bounds_actual_transport_call_count(monkeypatch, settings):
    settings.DELIVERY_DEFAULT_RETRY_DELAY_SECONDS = 0

    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    delivery = create_delivery(
        workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK, max_attempts=2
    )
    WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    fake_transport, calls = _fake_transport(raise_exc=WebhookTimeoutError())
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    for _ in range(5):
        try:
            claimed, token = claim_delivery(delivery_id=delivery.id)
        except DeliveryNotClaimableError:
            break
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert len(calls) == 2
    assert delivery.attempt_count == 2
    assert delivery.status == DeliveryStatus.FAILED


# ---------------------------------------------------------------------------
# Disabled endpoint (section 34)
# ---------------------------------------------------------------------------


def test_disabled_endpoint_never_reaches_transport(monkeypatch):
    endpoint = WebhookEndpointFactory(status=WebhookEndpointStatus.DISABLED)
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    def _fail_if_called(**kwargs):
        raise AssertionError("transport must never be called for a disabled endpoint")

    monkeypatch.setattr("webhooks.services.send_pinned_request", _fail_if_called)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == WebhookEndpointDisabledError.code


# ---------------------------------------------------------------------------
# SSRF blocked at send time never calls transport (section 50, cross-ref)
# ---------------------------------------------------------------------------


def test_ssrf_blocked_destination_never_calls_transport(monkeypatch):
    endpoint = WebhookEndpointFactory(url="https://example.com/hook")
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )

    def _blocked(hostname, port):
        raise WebhookDestinationBlockedError()

    monkeypatch.setattr("webhooks.services.resolve_and_validate", _blocked)

    def _fail_if_called(**kwargs):
        raise AssertionError("transport must never be called for an SSRF-blocked destination")

    monkeypatch.setattr("webhooks.services.send_pinned_request", _fail_if_called)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == "webhook_destination_blocked"


# ---------------------------------------------------------------------------
# Secret rotation mid-flight (section 35)
# ---------------------------------------------------------------------------


def test_secret_rotated_between_creation_and_send_uses_current_secret(monkeypatch):
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    _, new_secret = rotate_secret(workspace=endpoint.workspace, endpoint=endpoint, actor=None)

    fake_transport, calls = _fake_transport(status=204)
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    sent = calls[0]
    timestamp = int(sent["headers"]["X-SupportPilot-Timestamp"])
    expected = sign(secret=new_secret, timestamp=timestamp, raw_body=sent["body"])
    assert sent["headers"]["X-SupportPilot-Signature"] == expected
    # The event body itself is unchanged by the rotation.

    assert json.loads(sent["body"])["id"] == str(event.id)


# ---------------------------------------------------------------------------
# Event payload / snapshot immutability (section 8, 63)
# ---------------------------------------------------------------------------


def test_event_snapshot_survives_source_mutation(monkeypatch):
    endpoint = WebhookEndpointFactory()
    source_summary = {"reason": "refund over threshold"}
    event = WebhookEventFactory(workspace=endpoint.workspace, payload_snapshot=dict(source_summary))
    delivery = _delivery_for(endpoint, event, monkeypatch)

    # Mutate what would be the "source" business object's data — the
    # WebhookEvent row must not reflect it.
    source_summary["reason"] = "mutated after the fact"

    fake_transport, calls = _fake_transport(status=204)
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)
    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    body = json.loads(calls[0]["body"])
    assert body["data"]["reason"] == "refund over threshold"


# ---------------------------------------------------------------------------
# Secret-safe logging (section 32, 65-66)
# ---------------------------------------------------------------------------


def test_unexpected_transport_exception_never_logs_secret_or_signing_key(monkeypatch, caplog):
    secret_marker = "SUPER_SECRET_WEBHOOK_ERROR_123"
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    def _boom(**kwargs):
        raise RuntimeError(secret_marker)

    monkeypatch.setattr("webhooks.services.send_pinned_request", _boom)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    with caplog.at_level(logging.DEBUG, logger="supportpilot"):
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    assert secret_marker not in caplog.text
    assert TEST_SECRET not in caplog.text
    for record in caplog.records:
        assert record.exc_info is None

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == UNEXPECTED_ERROR_CODE
    assert secret_marker not in delivery.last_error_code
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert secret_marker not in attempt.safe_error_code


def test_signing_secret_never_appears_in_logs_on_success_or_failure(monkeypatch, caplog):
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)
    fake_transport, _calls = _fake_transport(status=204)
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    with caplog.at_level(logging.DEBUG, logger="supportpilot"):
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    assert TEST_SECRET not in caplog.text


# ---------------------------------------------------------------------------
# Additional coverage: update/status/rotate edge cases, missing delivery
# ---------------------------------------------------------------------------


def test_update_endpoint_can_change_url_and_event_types(monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    endpoint = WebhookEndpointFactory()
    updated = update_endpoint(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        actor=None,
        url="https://new.example.com/hook",
        subscribed_event_types=[WebhookEventType.HANDOFF_CREATED],
    )
    assert updated.url == "https://new.example.com/hook"
    assert updated.subscribed_event_types == [WebhookEventType.HANDOFF_CREATED]


def test_update_endpoint_with_no_fields_is_a_no_op():
    endpoint = WebhookEndpointFactory()
    updated = update_endpoint(workspace=endpoint.workspace, endpoint=endpoint, actor=None)
    assert updated is endpoint


def test_set_endpoint_status_rejects_invalid_value():
    endpoint = WebhookEndpointFactory()
    with pytest.raises(ValueError):
        set_endpoint_status(
            workspace=endpoint.workspace, endpoint=endpoint, actor=None, status="bogus"
        )


def test_missing_signing_secret_is_terminal_and_never_calls_transport(monkeypatch):
    endpoint = WebhookEndpointFactory()
    endpoint.encrypted_signing_secret = ""
    endpoint.save(update_fields=["encrypted_signing_secret"])
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    def _fail_if_called(**kwargs):
        raise AssertionError("transport must never be called without a signing secret")

    monkeypatch.setattr("webhooks.services.send_pinned_request", _fail_if_called)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == "webhook_signing_not_configured"


def test_corrupt_signing_secret_is_terminal(monkeypatch):
    endpoint = WebhookEndpointFactory()
    endpoint.encrypted_signing_secret = "not-a-valid-fernet-token"
    endpoint.save(update_fields=["encrypted_signing_secret"])
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == "webhook_signing_not_configured"


def test_missing_webhook_delivery_row_is_a_defensive_terminal_failure(monkeypatch):
    """A Delivery with channel=WEBHOOK but no ``WebhookDelivery`` row is a
    data-integrity gap, not a real-world outcome this block's own producer
    can create — exercised directly against the handler."""
    workspace = WebhookEndpointFactory().workspace
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    delivery = create_delivery(workspace=workspace, channel=DeliveryChannel.WEBHOOK)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == "webhook_delivery_missing"
