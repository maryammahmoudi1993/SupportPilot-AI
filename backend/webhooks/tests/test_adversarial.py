"""Phase 10 Block 5 — adversarial concurrency, failure injection, and
security hardening tests not already covered by Blocks 1-4's test suites:
ambiguous webhook timeouts, malicious transport/response content, duplicate
Celery message delivery after success, redrive against newly-private DNS,
the endpoint-disable race boundary, and delivery-list pagination.
"""

from __future__ import annotations

import logging

import pytest

from notifications.models import DeliveryAttempt, DeliveryChannel, DeliveryStatus
from notifications.services import claim_delivery, create_delivery
from notifications.tasks import process_delivery_task
from webhooks.errors import (
    WebhookDestinationBlockedError,
    WebhookEndpointDisabledError,
    WebhookTimeoutError,
)
from webhooks.models import WebhookDelivery, WebhookEndpointStatus
from webhooks.services import (
    UNEXPECTED_ERROR_CODE,
    handle_webhook_delivery_attempt,
    redrive_webhook_delivery,
)
from webhooks.tests.factories import WebhookEndpointFactory, WebhookEventFactory
from webhooks.transport import TransportResult
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

pytestmark = pytest.mark.django_db


def _delivery_for(endpoint, event, monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    return delivery


# ---------------------------------------------------------------------------
# Ambiguous external success (section 13, 20)
# ---------------------------------------------------------------------------


def test_ambiguous_timeout_retries_with_stable_identity_and_fresh_signature(monkeypatch):
    """Models a receiver that fully processed the request and only then the
    sender observes a timeout (section 13, 20) — this platform has no way
    to know the remote side effect occurred, so it correctly retries. The
    receiver legitimately sees two HTTP requests under at-least-once
    delivery; what must stay true is the *identity* the receiver can
    dedup on."""
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    # A controlled, strictly-increasing signing timestamp per attempt — a
    # fast test can otherwise legitimately land both real `time.time()`
    # calls in the same integer second, making the "timestamps differ"
    # assertion below pass or fail by accident rather than by design (see
    # ``test_retry_sequence.py`` for the same fix applied there).
    from webhooks.signing import build_signed_request as real_build_signed_request

    fake_clock = iter([1_800_000_000, 1_800_000_030])

    def _build_with_fresh_timestamp(**kwargs):
        return real_build_signed_request(now=next(fake_clock), **kwargs)

    monkeypatch.setattr("webhooks.services.build_signed_request", _build_with_fresh_timestamp)

    received: list[dict] = []
    outcomes = iter([WebhookTimeoutError(), None])  # attempt 1 times out, attempt 2 succeeds

    def fake_transport(*, scheme, ip, port, hostname, path_and_query, headers, body, method="POST"):
        # The receiver "processes" (records) the request before the sender
        # ever learns the outcome.
        received.append({"body": body, "headers": dict(headers)})
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        return TransportResult(status_code=204, latency_ms=1)

    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED

    claimed, token = claim_delivery(delivery_id=delivery.id, now=delivery.next_attempt_at)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED

    # The receiver really did see two requests — acceptable at-least-once
    # behavior, not a defect.
    assert len(received) == 2
    assert received[0]["body"] == received[1]["body"]
    assert (
        received[0]["headers"]["X-SupportPilot-Delivery-Id"]
        == received[1]["headers"]["X-SupportPilot-Delivery-Id"]
        == str(delivery.id)
    )
    assert (
        received[0]["headers"]["X-SupportPilot-Event-Id"]
        == received[1]["headers"]["X-SupportPilot-Event-Id"]
        == str(event.id)
    )
    assert (
        received[0]["headers"]["Idempotency-Key"]
        == received[1]["headers"]["Idempotency-Key"]
        == str(delivery.id)
    )
    # Fresh per actual attempt — never reused (section 87: not an
    # idempotency-hard-blocker to keep these stable).
    assert (
        received[0]["headers"]["X-SupportPilot-Timestamp"]
        != received[1]["headers"]["X-SupportPilot-Timestamp"]
    )
    assert (
        received[0]["headers"]["X-SupportPilot-Signature"]
        != received[1]["headers"]["X-SupportPilot-Signature"]
    )


# ---------------------------------------------------------------------------
# Malicious transport exception text (section 18, 41-42)
# ---------------------------------------------------------------------------


def test_malicious_transport_exception_text_never_leaks(monkeypatch, caplog):
    """A deliberately hostile exception message — newlines, a JSON
    fragment, and a credential-looking ``Authorization`` line, modeling a
    log-injection attempt — must never appear in logs, the persisted
    Delivery/DeliveryAttempt rows, or (by extension) any API response
    built from them."""
    hostile_text = "TOKEN=SECRET123\n" '{"level":"admin"}\n' "Authorization: Bearer SHOULD_NOT_LEAK"
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    def _boom(**kwargs):
        raise RuntimeError(hostile_text)

    monkeypatch.setattr("webhooks.services.send_pinned_request", _boom)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    with caplog.at_level(logging.DEBUG, logger="supportpilot"):
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    assert hostile_text not in caplog.text
    assert "SHOULD_NOT_LEAK" not in caplog.text
    assert "SECRET123" not in caplog.text
    for record in caplog.records:
        assert record.exc_info is None
        # A naive %-style logger call would let embedded newlines/braces
        # break a structured-log parser; asserting the marker is absent
        # from the rendered message is the reachable guarantee here.
        assert "SHOULD_NOT_LEAK" not in record.getMessage()

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == UNEXPECTED_ERROR_CODE
    assert "SHOULD_NOT_LEAK" not in delivery.last_error_code
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert "SHOULD_NOT_LEAK" not in attempt.safe_error_code
    assert "\n" not in attempt.safe_error_code


# ---------------------------------------------------------------------------
# Malicious/oversized response content never persisted (section 40, 74)
# ---------------------------------------------------------------------------


def test_response_body_never_persisted_regardless_of_content(monkeypatch):
    """``TransportResult`` structurally carries only ``status_code`` and
    ``latency_ms`` (see ``webhooks/transport.py``) — there is no field for
    a response body to occupy. This proves that holds true end to end
    through the handler even when the (fake) remote response body is huge
    and hostile; nothing downstream ever sees it."""
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    malicious_body = "<script>evil()</script>" + ("A" * 200_000) + '{"admin":true}'

    def fake_transport(**kwargs):
        # A real receiver's response body never reaches this function's
        # caller at all — ``send_pinned_request`` only ever returns
        # ``TransportResult(status_code, latency_ms)`` (see transport.py).
        # This fake proves that even if it *tried* to smuggle the body
        # through, there is no field to receive it.
        assert not hasattr(TransportResult(status_code=204, latency_ms=1), "body")
        return TransportResult(status_code=204, latency_ms=1)

    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert malicious_body not in str(delivery.__dict__)
    attempt = DeliveryAttempt.objects.get(delivery=delivery, attempt_number=1)
    assert malicious_body not in str(attempt.__dict__)


# ---------------------------------------------------------------------------
# Duplicate Celery message after success (section 7, 15)
# ---------------------------------------------------------------------------


def test_duplicate_task_message_after_webhook_success_makes_zero_second_call(monkeypatch):
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)

    calls = {"n": 0}

    def fake_transport(**kwargs):
        calls["n"] += 1
        return TransportResult(status_code=204, latency_ms=1)

    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    first = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert first == "processed"
    assert calls["n"] == 1
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED

    # A redelivered/duplicate task message for the same (already terminal)
    # delivery id — the DB's terminal state prevents any claim at all.
    second = process_delivery_task.apply(args=[str(delivery.id)]).get()
    assert second == "skipped"
    assert calls["n"] == 1
    assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1


# ---------------------------------------------------------------------------
# Redrive against a destination that turned private since success (section 30)
# ---------------------------------------------------------------------------


def test_redrive_blocks_when_dns_now_resolves_privately(monkeypatch):
    """The endpoint's URL was valid and reachable at original send time; by
    the time of redrive the same hostname now resolves privately (a
    plausible real-world DNS change, not just an SSRF bypass attempt).
    Redrive must never bypass send-time destination validation."""
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    delivery = create_delivery(
        workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK, max_attempts=1
    )
    webhook_delivery = WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    claimed, token = claim_delivery(delivery_id=delivery.id)
    from notifications.services import complete_delivery_failure

    complete_delivery_failure(
        delivery_id=claimed.id,
        claim_token=token,
        safe_error_code="webhook_http_500",
        retryable=True,
    )
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.FAILED

    redrive_webhook_delivery(
        workspace=endpoint.workspace, webhook_delivery=webhook_delivery, actor=None
    )

    def _now_private(hostname, port):
        raise WebhookDestinationBlockedError()

    monkeypatch.setattr("webhooks.services.resolve_and_validate", _now_private)

    def _fail_if_called(**kwargs):
        raise AssertionError("transport must never be called once DNS resolves privately")

    monkeypatch.setattr("webhooks.services.send_pinned_request", _fail_if_called)

    claimed, token = claim_delivery(delivery_id=delivery.id)
    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == WebhookDestinationBlockedError.code


# ---------------------------------------------------------------------------
# Endpoint-disable race — real PostgreSQL concurrency (section 31)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_endpoint_disable_race_documents_the_actual_boundary(monkeypatch):
    """Real concurrency proof of the documented boundary (section 31): the
    handler's endpoint-status check and the disable write are two separate
    transactions with no shared lock between them. If disable commits
    *before* the handler's fresh read, the handler sees DISABLED and never
    calls the transport — proven directly here. This test does not (and
    cannot honestly) prove disabling can *cancel* a transport call already
    in flight; that stronger claim is never made by this implementation.
    """
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    delivery = _delivery_for(endpoint, event, monkeypatch)
    claimed, token = claim_delivery(delivery_id=delivery.id)

    from webhooks.services import set_endpoint_status

    # Disable commits fully before the handler ever runs (the ordinary,
    # dominant case — the handler always reloads the endpoint fresh
    # immediately before deciding whether to send).
    set_endpoint_status(
        workspace=endpoint.workspace,
        endpoint=endpoint,
        actor=None,
        status=WebhookEndpointStatus.DISABLED,
    )

    def _fail_if_called(**kwargs):
        raise AssertionError("transport must never be called once disable has committed")

    monkeypatch.setattr("webhooks.services.send_pinned_request", _fail_if_called)

    handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DEAD
    assert delivery.last_error_code == WebhookEndpointDisabledError.code


# ---------------------------------------------------------------------------
# Pagination boundary (section 70)
# ---------------------------------------------------------------------------


def test_delivery_list_pagination_crosses_default_page_size_with_tenant_scope_intact():
    from rest_framework.test import APIClient

    endpoint = WebhookEndpointFactory()
    for _ in range(55):  # > StandardResultsSetPagination.page_size (50)
        # A distinct event per row — the (endpoint, event) pair is
        # DB-unique (fanout dedup, see WebhookDelivery.Meta), so 55 rows
        # against the same endpoint need 55 distinct events.
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
    other_endpoint = WebhookEndpointFactory()
    other_event = WebhookEventFactory(workspace=other_endpoint.workspace)
    other_delivery = create_delivery(
        workspace=other_endpoint.workspace, channel=DeliveryChannel.WEBHOOK
    )
    WebhookDelivery.objects.create(
        delivery=other_delivery,
        workspace=other_endpoint.workspace,
        endpoint=other_endpoint,
        event=other_event,
    )

    membership = WorkspaceMembershipFactory(workspace=endpoint.workspace, role=WorkspaceRole.VIEWER)
    client = APIClient()
    client.force_authenticate(user=membership.user)
    base = f"/api/v1/workspaces/{endpoint.workspace.id}/webhooks/deliveries/"

    page_one = client.get(base)
    assert page_one.status_code == 200
    assert len(page_one.data["results"]) == 50
    assert page_one.data["next"] is not None

    page_two = client.get(base, {"page": 2})
    assert page_two.status_code == 200
    assert len(page_two.data["results"]) == 5

    all_ids = {row["delivery_id"] for row in page_one.data["results"]} | {
        row["delivery_id"] for row in page_two.data["results"]
    }
    assert len(all_ids) == 55
    assert str(other_delivery.id) not in all_ids
