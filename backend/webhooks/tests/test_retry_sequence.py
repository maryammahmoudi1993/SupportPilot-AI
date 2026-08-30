"""Full webhook retry sequences through the Block 4 recovery boundary
(section 24, 52-53): 500 -> 500 -> 204 with correct exponential backoff,
stable identity (event id/delivery id/Idempotency-Key/raw body) across every
attempt, a *fresh* timestamp and recomputed signature per attempt (the
signing scheme is HMAC(secret, timestamp + "." + raw_body) — the body is
what must stay byte-identical across retries, never the signature, which is
only ever a stale replay if it were reused), and per-attempt DNS
re-validation — plus a disabled endpoint staying unsent through the sweeper.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from notifications.models import (
    AttemptStatus,
    Delivery,
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
)
from notifications.recovery import dispatch_due_deliveries
from notifications.services import claim_delivery, create_delivery
from notifications.tasks import process_delivery_task
from webhooks.errors import WebhookEndpointDisabledError
from webhooks.models import WebhookDelivery, WebhookEndpointStatus
from webhooks.services import handle_webhook_delivery_attempt
from webhooks.signing import build_signed_request, sign
from webhooks.tests.factories import TEST_SECRET, WebhookEndpointFactory, WebhookEventFactory
from webhooks.transport import TransportResult

pytestmark = pytest.mark.django_db(transaction=True)


def _delivery_for(endpoint, event, monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    return delivery


def test_500_500_204_sequence_has_correct_backoff_and_stable_identity(monkeypatch, settings):
    settings.DELIVERY_RETRY_BASE_DELAY_SECONDS = 30
    settings.DELIVERY_RETRY_MAX_DELAY_SECONDS = 3600
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    dns_calls: list[str] = []

    def _resolve(hostname, port):
        dns_calls.append(hostname)
        return "93.184.216.34"

    monkeypatch.setattr("webhooks.services.resolve_and_validate", _resolve)

    # A fresh, strictly-increasing signing timestamp per attempt — proves
    # the signature is genuinely recomputed from that attempt's own
    # timestamp, not frozen from the first attempt. Real `time.time()` calls
    # in a fast test can legitimately collide on the same integer second,
    # which would make "signatures differ" pass or fail by accident rather
    # than by design (see the docstring above), so this wraps the real
    # ``build_signed_request`` and injects an explicit, controlled ``now``
    # instead of patching the global ``time`` module (which would also
    # affect the logging module's own timestamps).
    real_build_signed_request = build_signed_request
    fake_clock = iter([1_700_000_000, 1_700_000_030, 1_700_000_090])

    def _build_with_fresh_timestamp(**kwargs):
        return real_build_signed_request(now=next(fake_clock), **kwargs)

    monkeypatch.setattr("webhooks.services.build_signed_request", _build_with_fresh_timestamp)

    responses = iter([500, 500, 204])
    bodies: list[bytes] = []
    signatures: list[str] = []
    timestamps: list[str] = []

    def fake_transport(*, scheme, ip, port, hostname, path_and_query, headers, body, method="POST"):
        bodies.append(body)
        signatures.append(headers["X-SupportPilot-Signature"])
        timestamps.append(headers["X-SupportPilot-Timestamp"])
        return TransportResult(status_code=next(responses), latency_ms=1)

    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    # ``complete_delivery_failure`` always computes its own real
    # ``timezone.now()`` internally (the webhook handler never overrides
    # it), and this test runs in well under a second — so the backoff
    # window for each attempt is bound relative to a wall-clock timestamp
    # captured immediately before *that* attempt's call, not to the
    # (artificially future) ``next_attempt_at`` used only to satisfy claim
    # eligibility (section 13, 39: no real ``sleep()``, so the delivery is
    # explicitly re-dated to "due now" before each claim instead).

    # Attempt 1: 500 -> retryable, backoff = base (30s).
    call_time_1 = timezone.now()
    claimed, token = claim_delivery(delivery_id=delivery.id, now=call_time_1)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED
    assert delivery.next_attempt_at > call_time_1 + timedelta(seconds=25)
    assert delivery.next_attempt_at < call_time_1 + timedelta(seconds=35)

    # Attempt 2: 500 -> retryable, backoff doubles (60s). Force the row due
    # now rather than waiting out the real 30s scheduled above.
    Delivery.objects.filter(pk=delivery.id).update(next_attempt_at=timezone.now())
    call_time_2 = timezone.now()
    claimed, token = claim_delivery(delivery_id=delivery.id, now=call_time_2)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED
    assert delivery.next_attempt_at > call_time_2 + timedelta(seconds=55)
    assert delivery.next_attempt_at < call_time_2 + timedelta(seconds=65)

    # Attempt 3: 204 -> delivered.
    Delivery.objects.filter(pk=delivery.id).update(next_attempt_at=timezone.now())
    claimed, token = claim_delivery(delivery_id=delivery.id, now=timezone.now())
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.attempt_count == 3

    # The raw event body is stable across all three attempts (section 24) —
    # never re-serialized, so its bytes are identical every time.
    assert len(bodies) == 3
    assert bodies[0] == bodies[1] == bodies[2]

    # The timestamp and signature are the opposite: each attempt gets a
    # fresh timestamp (from this test's controlled clock) and therefore a
    # freshly-recomputed signature — reusing a signature across attempts
    # would mean the timestamp was frozen and never actually protecting
    # against replay, which is not this scheme's design.
    assert timestamps == ["1700000000", "1700000030", "1700000090"]
    assert len(set(signatures)) == 3, "each attempt must sign its own fresh timestamp"
    for ts, sig, body in zip(timestamps, signatures, bodies, strict=True):
        assert sig == sign(secret=TEST_SECRET, timestamp=int(ts), raw_body=body)

    assert dns_calls == ["example.com", "example.com", "example.com"]  # re-resolved every attempt
    assert WebhookDelivery.objects.filter(event=event).count() == 1  # still one logical delivery
    assert (
        DeliveryAttempt.objects.filter(delivery=delivery, status=AttemptStatus.SUCCEEDED).count()
        == 1
    )
    assert (
        DeliveryAttempt.objects.filter(delivery=delivery, status=AttemptStatus.FAILED).count() == 2
    )


def test_disabled_endpoint_stays_unsent_through_the_recovery_sweeper(monkeypatch):
    endpoint = WebhookEndpointFactory(status=WebhookEndpointStatus.DISABLED)
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    def _fail_if_called(**kwargs):
        raise AssertionError("transport must never be called for a disabled endpoint")

    monkeypatch.setattr("webhooks.services.send_pinned_request", _fail_if_called)

    def _synchronous_dispatch(delivery_id, **kwargs):
        process_delivery_task.apply(args=[delivery_id]).get()

    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing", _synchronous_dispatch
    )

    dispatch_due_deliveries()

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == WebhookEndpointDisabledError.code
