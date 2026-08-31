"""Phase 11 Block 4 remediation: direct delivery-span privacy inspection,
a genuine cross-process proof of the ``mostrecent`` delivery gauges, the
Celery-scrape/DB-gauge isolation guarantee, and integrated
state-plus-telemetry end-to-end scenarios.

Complements ``test_delivery_instrumentation.py`` rather than duplicating
it: that file already covers per-property unit assertions (Prometheus text
output, transaction rollback, concurrency/no-double-count) for every Block
4 metric in isolation. This file closes the three specific verification
gaps the remediation brief identified:

1. the ``delivery.attempt`` span was previously only ever checked via
   Prometheus text output, never via direct ``InMemorySpanExporter``
   inspection of the actual finished span (name/attributes/events/status);
2. the new ``multiprocess_mode="mostrecent"`` Gauges were previously only
   proven correct within a single test process — never across genuine
   separate OS processes, the property the mode itself exists for;
3. several Phase 10 delivery flows (500 -> retry -> 204, broker-failure
   recovery, expired-claim reclaim, redrive) were proven for business state
   and for telemetry in separate, narrower tests rather than as one
   continuous state-plus-telemetry flow.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone
from prometheus_client.parser import text_string_to_metric_families

from integrations.errors import IntegrationTimeoutError
from integrations.providers.base import NormalizedNotification
from notifications.models import (
    AttemptStatus,
    Delivery,
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
)
from notifications.notification_delivery import (
    create_or_reuse_notification_delivery,
    handle_notification_delivery_attempt,
)
from notifications.recovery import dispatch_due_deliveries, recover_expired_delivery_claims
from notifications.services import claim_delivery, complete_delivery_failure, create_delivery
from notifications.tasks import process_delivery_task
from observability.metrics import METRIC_NAMESPACE, render_metrics
from tools.tests.factories import ToolExecutionFactory
from webhooks.errors import WebhookDeliveryNotRedrivableError
from webhooks.models import WebhookDelivery
from webhooks.services import handle_webhook_delivery_attempt, redrive_webhook_delivery
from webhooks.tests.factories import WebhookEndpointFactory, WebhookEventFactory
from webhooks.transport import TransportResult

SPAN_SECRET_MARKER = "SUPER_SECRET_DELIVERY_SPAN_984231"
EXCEPTION_SECRET_MARKER = "SUPER_SECRET_EXTERNAL_ERROR_729415"

_ATTEMPT_SPAN_SAFE_KEYS = {"delivery.channel", "attempt.number", "supportpilot.outcome"}


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


def _sum(metric_name: str, **labels) -> float:
    return float(
        sum(
            s.value
            for s in _samples(metric_name)
            if all(s.labels.get(k) == v for k, v in labels.items())
        )
    )


def _assert_marker_absent_from_every_span(spans, marker: str) -> None:
    for span in spans:
        assert marker not in span.name
        for key, value in span.attributes.items():
            assert marker not in key
            assert marker not in str(value)
        for event in span.events:
            assert marker not in event.name
            for value in event.attributes.values():
                assert marker not in str(value)
        if span.status.description:
            assert marker not in span.status.description


# ---------------------------------------------------------------------------
# 1. Direct delivery span privacy inspection (hard gate)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDeliverySpanPrivacyDirectInspection:
    def test_webhook_attempt_span_never_leaks_url_payload_or_secret(self, traced, monkeypatch):
        endpoint = WebhookEndpointFactory(url=f"https://example.com/{SPAN_SECRET_MARKER}")
        event = WebhookEventFactory(
            workspace=endpoint.workspace, payload_snapshot={"note": SPAN_SECRET_MARKER}
        )
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
        monkeypatch.setattr(
            "webhooks.services.send_pinned_request",
            lambda **kwargs: TransportResult(status_code=204, latency_ms=1),
        )
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )

        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

        finished = traced.get_finished_spans()
        attempt_spans = [s for s in finished if s.name == "delivery.attempt"]
        assert len(attempt_spans) == 1
        span = attempt_spans[0]
        assert set(span.attributes.keys()) == _ATTEMPT_SPAN_SAFE_KEYS
        assert span.attributes["delivery.channel"] == "webhook"
        assert span.attributes["supportpilot.outcome"] == "succeeded"
        _assert_marker_absent_from_every_span(finished, SPAN_SECRET_MARKER)
        assert SPAN_SECRET_MARKER not in _metrics_text()

    def test_notification_attempt_span_never_leaks_recipient_subject_or_body(
        self, traced, monkeypatch
    ):
        tool_execution = ToolExecutionFactory()
        notification_delivery = create_or_reuse_notification_delivery(
            tool_execution=tool_execution,
            workspace=tool_execution.workspace,
            recipient_email=f"user+{SPAN_SECRET_MARKER}@example.com",
            subject=SPAN_SECRET_MARKER,
            body=SPAN_SECRET_MARKER,
        )
        monkeypatch.setattr(
            "notifications.notification_delivery.send_notification",
            lambda **kwargs: NormalizedNotification(message_id="msg-1", status="sent"),
        )
        claimed, token = claim_delivery(delivery_id=notification_delivery.delivery_id)

        handle_notification_delivery_attempt(delivery=claimed, claim_token=token)

        finished = traced.get_finished_spans()
        attempt_spans = [s for s in finished if s.name == "delivery.attempt"]
        assert len(attempt_spans) == 1
        span = attempt_spans[0]
        assert set(span.attributes.keys()) == _ATTEMPT_SPAN_SAFE_KEYS
        assert span.attributes["delivery.channel"] == "notification"
        assert span.attributes["supportpilot.outcome"] == "succeeded"
        _assert_marker_absent_from_every_span(finished, SPAN_SECRET_MARKER)
        assert SPAN_SECRET_MARKER not in _metrics_text()


# ---------------------------------------------------------------------------
# 2. Raw exception text must never reach the span (or logs/metrics)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestRawExceptionNeverReachesSpan:
    def test_webhook_transport_exception_marker_never_reaches_span_log_or_metrics(
        self, traced, monkeypatch, caplog
    ):
        import logging

        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")

        def _boom(**kwargs):
            raise RuntimeError(EXCEPTION_SECRET_MARKER)

        monkeypatch.setattr("webhooks.services.send_pinned_request", _boom)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        claimed, token = claim_delivery(delivery_id=delivery.id)

        with caplog.at_level(logging.DEBUG):
            handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

        # Business semantics unchanged: an unclassified transport exception
        # fails closed (never retried) — same as before this remediation.
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DEAD
        assert delivery.last_error_code == "webhook_delivery_unexpected_error"

        finished = traced.get_finished_spans()
        attempt_spans = [s for s in finished if s.name == "delivery.attempt"]
        assert len(attempt_spans) == 1
        assert attempt_spans[0].attributes["supportpilot.outcome"] == "failed"
        _assert_marker_absent_from_every_span(finished, EXCEPTION_SECRET_MARKER)
        for record in caplog.records:
            assert EXCEPTION_SECRET_MARKER not in record.getMessage()
        assert EXCEPTION_SECRET_MARKER not in _metrics_text()

    def test_notification_provider_exception_marker_never_reaches_span_log_or_metrics(
        self, traced, monkeypatch, caplog
    ):
        import logging

        tool_execution = ToolExecutionFactory()
        notification_delivery = create_or_reuse_notification_delivery(
            tool_execution=tool_execution,
            workspace=tool_execution.workspace,
            recipient_email="user@example.com",
            subject="subject",
            body="body",
        )

        def _boom(**kwargs):
            raise RuntimeError(EXCEPTION_SECRET_MARKER)

        monkeypatch.setattr("notifications.notification_delivery.send_notification", _boom)
        claimed, token = claim_delivery(delivery_id=notification_delivery.delivery_id)

        with caplog.at_level(logging.DEBUG):
            handle_notification_delivery_attempt(delivery=claimed, claim_token=token)

        claimed.refresh_from_db()
        assert claimed.status == DeliveryStatus.DEAD
        assert claimed.last_error_code == "notification_delivery_unexpected_error"

        finished = traced.get_finished_spans()
        attempt_spans = [s for s in finished if s.name == "delivery.attempt"]
        assert len(attempt_spans) == 1
        assert attempt_spans[0].attributes["supportpilot.outcome"] == "failed"
        _assert_marker_absent_from_every_span(finished, EXCEPTION_SECRET_MARKER)
        for record in caplog.records:
            assert EXCEPTION_SECRET_MARKER not in record.getMessage()
        assert EXCEPTION_SECRET_MARKER not in _metrics_text()


# ---------------------------------------------------------------------------
# 3. Genuine cross-process proof of the mostrecent delivery gauges
# ---------------------------------------------------------------------------


class TestMultiprocessGaugeCrossProcessProof:
    """Mirrors ``config/tests/test_celery_metrics.py::TestCrossProcessMultiprocessScrape``'s
    established real-subprocess pattern exactly, extended to prove the
    *newer-sample-wins* semantics ``multiprocess_mode="mostrecent"`` exists
    for. Each child process sets the gauge directly via
    ``.labels(...).set(...)`` — the same call
    ``refresh_delivery_backlog_gauges`` itself makes internally after its DB
    queries — because the property under test here is Prometheus's own
    multiprocess aggregation semantics for this metric *type*, not the DB
    query logic (already covered directly, in-process, by
    ``TestBacklogGauges`` in ``test_delivery_instrumentation.py``)."""

    def _run_child_setting_gauge(self, *, multiproc_dir, gauge_attr, channel, value):
        backend_root = str(Path(__file__).resolve().parent.parent.parent)
        child_script = textwrap.dedent(f"""
            import os
            os.environ["PROMETHEUS_MULTIPROC_DIR"] = {str(multiproc_dir)!r}
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
            import sys
            sys.path.insert(0, {backend_root!r})
            import django
            django.setup()
            from observability.metrics import {gauge_attr}
            {gauge_attr}.labels(channel={channel!r}).set({value!r})
            """)
        result = subprocess.run(
            [sys.executable, "-c", child_script], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stderr

    def _collect(self, multiproc_dir) -> str:
        from prometheus_client import CollectorRegistry, generate_latest, multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=str(multiproc_dir))
        return generate_latest(registry).decode("utf-8")

    @pytest.mark.parametrize(
        "gauge_attr,metric_name",
        [
            ("DELIVERY_DUE_COUNT", f"{METRIC_NAMESPACE}_delivery_due_count"),
            (
                "DELIVERY_EXPIRED_CLAIM_COUNT",
                f"{METRIC_NAMESPACE}_delivery_expired_claim_count",
            ),
            (
                "DELIVERY_OLDEST_DUE_AGE_SECONDS",
                f"{METRIC_NAMESPACE}_delivery_oldest_due_age_seconds",
            ),
        ],
    )
    def test_newer_process_sample_wins_under_mostrecent_mode(
        self, tmp_path, gauge_attr, metric_name
    ):
        multiproc_dir = tmp_path / f"gauge-mostrecent-{gauge_attr}"
        multiproc_dir.mkdir()

        # Process A (a "stale worker"): writes an old, larger value.
        self._run_child_setting_gauge(
            multiproc_dir=multiproc_dir, gauge_attr=gauge_attr, channel="webhook", value=50.0
        )
        body_after_a = self._collect(multiproc_dir)
        samples_a = [
            s
            for family in text_string_to_metric_families(body_after_a)
            for s in family.samples
            if s.name == metric_name and s.labels.get("channel") == "webhook"
        ]
        assert samples_a and samples_a[0].value == 50.0

        # Process B (a fresh, later process recomputing from the DB):
        # writes a newer, smaller value for the SAME gauge/label.
        self._run_child_setting_gauge(
            multiproc_dir=multiproc_dir, gauge_attr=gauge_attr, channel="webhook", value=3.0
        )
        body_after_b = self._collect(multiproc_dir)
        samples_b = [
            s
            for family in text_string_to_metric_families(body_after_b)
            for s in family.samples
            if s.name == metric_name and s.labels.get("channel") == "webhook"
        ]
        assert len(samples_b) == 1, "mostrecent must not fan out A and B into two series"
        # The rendered value must reflect B's newer sample (3), never A's
        # stale 50 and never their sum (53) — exactly why
        # ``multiprocess_mode="mostrecent"`` was chosen over the ``Gauge``
        # default (summing), which would report 53 here.
        assert samples_b[0].value == 3.0


# ---------------------------------------------------------------------------
# 4. Celery scrape must never trigger the DB-derived gauge refresh
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCeleryScrapeNeverTriggersDbGaugeRefresh:
    def test_render_metrics_never_calls_the_db_gauge_refresh(self, monkeypatch):
        """``config/celery_metrics.py``'s exposition listener calls
        ``render_metrics()`` directly (see that module's ``do_GET``) — never
        ``refresh_delivery_backlog_gauges``. Patch the refresh entry point to
        raise if called, then render through the exact function the Celery
        listener uses; a regression that started calling the DB refresh from
        inside ``render_metrics()`` would make every Celery child issue these
        queries on every scrape (the architecture violation section 20/21 of
        the original Block 4 brief exists to prevent) and would fail this
        test immediately."""
        import observability.metrics as metrics_module

        def _boom(**kwargs):
            raise AssertionError("render_metrics() must never call the DB gauge refresh")

        monkeypatch.setattr(metrics_module, "refresh_delivery_backlog_gauges", _boom)

        body = render_metrics()  # must not raise
        assert body

    def test_django_metrics_view_does_call_the_db_gauge_refresh(self, monkeypatch, settings):
        """The mirror-image proof: the one deliberate call site
        (``observability/views.py::metrics_view``) really does invoke it —
        confirming the isolation proved above is a deliberate architectural
        choice, not an accidental omission that happens to also cover the
        Django path."""
        from rest_framework.test import APIClient

        import observability.views as views_module

        calls = []
        monkeypatch.setattr(
            views_module, "refresh_delivery_backlog_gauges", lambda **kwargs: calls.append(1)
        )
        settings.OBSERVABILITY_METRICS_ENABLED = True
        settings.OBSERVABILITY_METRICS_TOKEN = "test-remediation-token"

        response = APIClient().get("/metrics/", HTTP_AUTHORIZATION="Bearer test-remediation-token")

        assert response.status_code == 200
        assert calls == [1]


# ---------------------------------------------------------------------------
# 5. Integrated state + telemetry E2E: webhook 500 -> retry -> 204
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestIntegratedE2EWebhookRetryThenSuccess:
    def test_500_then_204_produces_expected_business_state_and_telemetry_in_one_flow(
        self, monkeypatch
    ):
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )

        responses = iter([500, 204])
        monkeypatch.setattr(
            "webhooks.services.send_pinned_request",
            lambda **kwargs: TransportResult(status_code=next(responses), latency_ms=1),
        )

        before_attempts = _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="webhook")
        before_retries = _sum(f"{METRIC_NAMESPACE}_delivery_retries_total", channel="webhook")
        before_5xx = _sum(f"{METRIC_NAMESPACE}_webhook_responses_total", status_class="5xx")
        before_2xx = _sum(f"{METRIC_NAMESPACE}_webhook_responses_total", status_class="2xx")
        before_delivered = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total", channel="webhook", outcome="delivered"
        )
        before_e2e = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_delivery_end_to_end_duration_seconds_count")
            if s.labels.get("channel") == "webhook"
        )

        # Attempt 1: 500 -> RETRY_SCHEDULED.
        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.RETRY_SCHEDULED

        # Force due-now rather than sleeping out the real backoff window
        # (mirrors webhooks/tests/test_retry_sequence.py's own convention).
        Delivery.objects.filter(pk=delivery.id).update(next_attempt_at=timezone.now())

        # Attempt 2: 204 -> DELIVERED.
        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED
        assert delivery.attempt_count == 2
        assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 2
        assert (
            DeliveryAttempt.objects.filter(
                delivery=delivery, status=AttemptStatus.SUCCEEDED
            ).count()
            == 1
        )
        assert (
            DeliveryAttempt.objects.filter(delivery=delivery, status=AttemptStatus.FAILED).count()
            == 1
        )

        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="webhook")
            == before_attempts + 2
        )
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_retries_total", channel="webhook")
            == before_retries + 1
        )
        assert (
            _sum(f"{METRIC_NAMESPACE}_webhook_responses_total", status_class="5xx")
            == before_5xx + 1
        )
        assert (
            _sum(f"{METRIC_NAMESPACE}_webhook_responses_total", status_class="2xx")
            == before_2xx + 1
        )
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_terminal_total",
                channel="webhook",
                outcome="delivered",
            )
            == before_delivered + 1
        )
        after_e2e = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_delivery_end_to_end_duration_seconds_count")
            if s.labels.get("channel") == "webhook"
        )
        assert after_e2e == before_e2e + 1


# ---------------------------------------------------------------------------
# 6. Integrated state + telemetry E2E: broker failure -> recovery
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestIntegratedE2EBrokerFailureThenRecovery:
    def test_initial_broker_failure_then_sweeper_recovery_in_one_flow(self, monkeypatch):
        import notifications.tasks as tasks_module

        broker_down = {"value": True}
        real_delay = tasks_module.process_delivery_task.delay

        def _maybe_broker_down(*args, **kwargs):
            if broker_down["value"]:
                raise RuntimeError("broker unavailable")
            return real_delay(*args, **kwargs)

        monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _maybe_broker_down)

        before_broker_failures = _sum(
            f"{METRIC_NAMESPACE}_delivery_broker_publication_failures_total",
            channel="notification",
            source="initial",
        )
        before_attempts = _sum(
            f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification"
        )
        before_delivered = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total",
            channel="notification",
            outcome="delivered",
        )

        tool_execution = ToolExecutionFactory()
        notification_delivery = create_or_reuse_notification_delivery(
            tool_execution=tool_execution,
            workspace=tool_execution.workspace,
            recipient_email="user@example.com",
            subject="subject",
            body="body",
        )
        delivery = notification_delivery.delivery

        assert delivery.status == DeliveryStatus.PENDING
        assert delivery.attempt_count == 0
        assert not DeliveryAttempt.objects.filter(delivery=delivery).exists()
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_broker_publication_failures_total",
                channel="notification",
                source="initial",
            )
            == before_broker_failures + 1
        )
        # No phantom attempt from the broker failure alone.
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
            == before_attempts
        )

        # Broker recovers; the recovery sweeper republishes.
        broker_down["value"] = False
        Delivery.objects.filter(pk=delivery.id).update(next_attempt_at=timezone.now())
        monkeypatch.setattr(
            "notifications.notification_delivery.send_notification",
            lambda **kwargs: NormalizedNotification(message_id="msg-1", status="sent"),
        )
        dispatch_due_deliveries()
        # Drain the now-published task synchronously — represents the
        # worker actually picking it up, deterministically, rather than
        # depending on a live Celery consumer inside the test process
        # (mirrors the existing "two sweepers" test's own convention).
        process_delivery_task.apply(args=[str(delivery.id)]).get()

        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
            == before_attempts + 1
        )
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_terminal_total",
                channel="notification",
                outcome="delivered",
            )
            == before_delivered + 1
        )


# ---------------------------------------------------------------------------
# 7. Integrated state + telemetry E2E: expired claim -> reclaim -> terminal
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestIntegratedE2EExpiredClaimReclaimThenTerminal:
    def test_expired_claim_reclaim_then_delivered_in_one_flow(self, monkeypatch):
        def _synchronous_dispatch(delivery_id, **kwargs):
            process_delivery_task.apply(args=[delivery_id]).get()

        import notifications.recovery as recovery_module

        monkeypatch.setattr(
            recovery_module, "dispatch_delivery_for_processing", _synchronous_dispatch
        )

        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
        monkeypatch.setattr(
            "webhooks.services.send_pinned_request",
            lambda **kwargs: TransportResult(status_code=204, latency_ms=1),
        )
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        now = timezone.now()
        Delivery.objects.filter(pk=delivery.id).update(next_attempt_at=now - timedelta(minutes=10))
        _, stale_token = claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)
        Delivery.objects.filter(pk=delivery.id).update(lease_expires_at=now - timedelta(seconds=1))

        before_recoveries = _sum(
            f"{METRIC_NAMESPACE}_delivery_claim_recoveries_total", channel="webhook"
        )
        before_attempts = _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="webhook")
        before_delivered = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total", channel="webhook", outcome="delivered"
        )

        recover_expired_delivery_claims()

        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED
        old_attempt = DeliveryAttempt.objects.get(delivery=delivery, claim_token=stale_token)
        assert old_attempt.status == AttemptStatus.ABANDONED
        assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 2
        assert (
            DeliveryAttempt.objects.filter(
                delivery=delivery, status=AttemptStatus.SUCCEEDED
            ).count()
            == 1
        )

        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_claim_recoveries_total", channel="webhook")
            == before_recoveries + 1
        )
        # The reclaim is a genuine second ownership acquisition — one more
        # real attempt metric than before. The abandoned attempt is observed
        # separately (duration-only, outcome="abandoned"), never as a second
        # "attempt" increment.
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="webhook")
            == before_attempts + 1
        )
        # Exactly one terminal observation — no duplicate from the abandoned
        # attempt's own completion path (it is never routed through
        # complete_delivery_success/failure at all).
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_terminal_total",
                channel="webhook",
                outcome="delivered",
            )
            == before_delivered + 1
        )


# ---------------------------------------------------------------------------
# 8. Integrated state + telemetry E2E: redrive -> new attempt -> terminal
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestIntegratedE2ERedriveThenNewAttempt:
    def test_redrive_preserves_identity_and_history_then_a_new_attempt_delivers(self, monkeypatch):
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
        complete_delivery_failure(
            delivery_id=claimed.id,
            claim_token=token,
            safe_error_code="webhook_http_500",
            retryable=True,
        )
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.FAILED
        original_delivery_pk = delivery.id
        original_webhook_delivery_pk = webhook_delivery.id
        assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1

        before_created = _sum(f"{METRIC_NAMESPACE}_deliveries_created_total", channel="webhook")
        before_redrives = _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook")

        redrive_webhook_delivery(
            workspace=endpoint.workspace, webhook_delivery=webhook_delivery, actor=None
        )

        delivery.refresh_from_db()
        assert delivery.id == original_delivery_pk
        assert (
            WebhookDelivery.objects.get(pk=original_webhook_delivery_pk).delivery_id
            == original_delivery_pk
        )
        assert delivery.status == DeliveryStatus.PENDING
        # Attempt history preserved — never reset or deleted by a redrive.
        assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 1
        assert (
            _sum(f"{METRIC_NAMESPACE}_deliveries_created_total", channel="webhook")
            == before_created
        )
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook")
            == before_redrives + 1
        )

        before_attempts = _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="webhook")
        before_delivered = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total", channel="webhook", outcome="delivered"
        )
        monkeypatch.setattr(
            "webhooks.services.send_pinned_request",
            lambda **kwargs: TransportResult(status_code=204, latency_ms=1),
        )
        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED
        assert DeliveryAttempt.objects.filter(delivery=delivery).count() == 2
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="webhook")
            == before_attempts + 1
        )
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_terminal_total",
                channel="webhook",
                outcome="delivered",
            )
            == before_delivered + 1
        )

        # Repeated redrive against the now-DELIVERED (non-exhausted) delivery
        # is rejected and records no second successful redrive.
        webhook_delivery.refresh_from_db()
        before_second_redrive = _sum(
            f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook"
        )
        with pytest.raises(WebhookDeliveryNotRedrivableError):
            redrive_webhook_delivery(
                workspace=endpoint.workspace, webhook_delivery=webhook_delivery, actor=None
            )
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook")
            == before_second_redrive
        )


# ---------------------------------------------------------------------------
# 9. Ambiguous external success: real attempts represented accurately
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestAmbiguousExternalSuccessRepresentedAccurately:
    def test_two_real_attempts_are_recorded_across_a_retryable_failure_then_success(
        self, monkeypatch
    ):
        """Phase 10's delivery guarantee is at-least-once, never
        exactly-once (``docs/observability/slos.md``) — a provider timeout
        genuinely leaves the external side effect ambiguous (it may or may
        not have gone through), and Phase 10 already handles this via its
        committed-before-raising design (``notifications/services.py``).
        This test proves the metric layer represents that reality honestly:
        both real attempts are counted (never collapsed into one, never
        silently dropped), and nothing here claims or implies exactly-once
        delivery."""
        tool_execution = ToolExecutionFactory()
        notification_delivery = create_or_reuse_notification_delivery(
            tool_execution=tool_execution,
            workspace=tool_execution.workspace,
            recipient_email="user@example.com",
            subject="subject",
            body="body",
        )
        delivery = notification_delivery.delivery

        outcomes = iter(
            [
                IntegrationTimeoutError("provider timed out — outcome unknown"),
                None,  # second attempt succeeds
            ]
        )

        def _send(**kwargs):
            outcome = next(outcomes)
            if outcome is not None:
                raise outcome
            return NormalizedNotification(message_id="msg-1", status="sent")

        monkeypatch.setattr("notifications.notification_delivery.send_notification", _send)

        before_attempts = _sum(
            f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification"
        )
        before_delivered = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total",
            channel="notification",
            outcome="delivered",
        )

        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_notification_delivery_attempt(delivery=claimed, claim_token=token)
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.RETRY_SCHEDULED

        Delivery.objects.filter(pk=delivery.id).update(next_attempt_at=timezone.now())
        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_notification_delivery_attempt(delivery=claimed, claim_token=token)
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED

        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
            == before_attempts + 2
        )
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_terminal_total",
                channel="notification",
                outcome="delivered",
            )
            == before_delivered + 1
        )
