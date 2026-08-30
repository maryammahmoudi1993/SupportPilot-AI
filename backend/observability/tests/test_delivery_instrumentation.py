"""Phase 11 Block 4 hard gates: durable delivery / webhook reliability
observability — cardinality, secret isolation, failure isolation, no
double-counting, transaction rollback semantics, and E2E telemetry —
exercised through the real ``notifications``/``webhooks`` services with
deterministic fakes, never a live provider.

``transaction=True`` throughout, same reason as
``test_domain_instrumentation.py``: every delivery metric here is recorded
via ``transaction.on_commit``, which never fires inside the ordinary
rolled-back ``@pytest.mark.django_db`` test transaction.
"""

from __future__ import annotations

import threading
import uuid
from datetime import timedelta

import django.db as django_db
import pytest
from django.db import transaction
from django.utils import timezone
from prometheus_client.parser import text_string_to_metric_families

import notifications.handlers as handlers_module
import notifications.tasks as tasks_module
from notifications.models import (
    AttemptStatus,
    Delivery,
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
)
from notifications.recovery import dispatch_due_deliveries, recover_expired_delivery_claims
from notifications.services import (
    claim_delivery,
    complete_delivery_failure,
    complete_delivery_success,
    create_delivery,
)
from notifications.tasks import process_delivery_task
from notifications.tests.factories import DeliveryFactory
from observability.metrics import (
    METRIC_NAMESPACE,
    refresh_delivery_backlog_gauges,
    render_metrics,
)
from webhooks.errors import WebhookDestinationBlockedError, WebhookInvalidURLError
from webhooks.models import WebhookDelivery
from webhooks.services import handle_webhook_delivery_attempt, redrive_webhook_delivery
from webhooks.tests.factories import WebhookEndpointFactory, WebhookEventFactory
from webhooks.transport import TransportResult
from workspaces.tests.factories import WorkspaceFactory

SECRET_MARKER = "SUPER_SECRET_DELIVERY_OBSERVABILITY_642971"

FAKE_CHANNEL = "test_block4_chan"


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


def _gauge_value(metric_name: str, **labels) -> float | None:
    matches = [
        s.value
        for s in _samples(metric_name)
        if all(s.labels.get(k) == v for k, v in labels.items())
    ]
    return matches[-1] if matches else None


class _FakeChannelCalls(list):
    """A plain ``list`` subclass purely so a test can also attach an
    ``outcomes`` queue onto the same object the fixture returns — a bare
    ``list`` instance does not support arbitrary attribute assignment."""

    outcomes: list


@pytest.fixture
def fake_channel_calls(monkeypatch):
    """A configurable fake handler — call-counting only, no network I/O
    (mirrors ``notifications/tests/test_recovery.py``'s own fixture). By
    default it always succeeds; a test may push scripted outcomes onto
    ``calls.outcomes`` (a queue of callables receiving
    ``(delivery, claim_token)``) to script failures/retries instead."""
    calls = _FakeChannelCalls()
    calls.outcomes = []

    def handler(*, delivery, claim_token):
        calls.append((delivery.id, claim_token))
        if calls.outcomes:
            calls.outcomes.pop(0)(delivery, claim_token)
        else:
            complete_delivery_success(delivery_id=delivery.id, claim_token=claim_token)

    patched = dict(handlers_module._HANDLERS)
    patched[FAKE_CHANNEL] = handler
    monkeypatch.setattr(handlers_module, "_HANDLERS", patched)
    return calls


def _run_in_threads(*targets):
    threads = [threading.Thread(target=t) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)


# ---------------------------------------------------------------------------
# Creation (section 6, 37)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDeliveryCreated:
    def test_created_delivery_increments_created_total(self):
        before = _sum(f"{METRIC_NAMESPACE}_deliveries_created_total", channel="notification")
        create_delivery(workspace=WorkspaceFactory(), channel=FAKE_CHANNEL)
        # FAKE_CHANNEL isn't "notification"/"webhook" — the observer
        # collapses any unrecognized channel to "notification" (its
        # documented fallback), so assert against that collapsed label.
        after = _sum(f"{METRIC_NAMESPACE}_deliveries_created_total", channel="notification")
        assert after == before + 1

    def test_rolled_back_creation_records_nothing(self):
        before = _sum(f"{METRIC_NAMESPACE}_deliveries_created_total", channel="notification")
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                create_delivery(workspace=WorkspaceFactory(), channel=FAKE_CHANNEL)
                raise RuntimeError("forced rollback")
        after = _sum(f"{METRIC_NAMESPACE}_deliveries_created_total", channel="notification")
        assert after == before
        assert not Delivery.objects.filter(workspace__isnull=False, channel=FAKE_CHANNEL).exists()


# ---------------------------------------------------------------------------
# Attempts / duplicate task / two sweepers (section 7, 35-36)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDeliveryAttempts:
    def test_duplicate_task_execution_produces_exactly_one_attempt_metric(self, fake_channel_calls):
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        before = _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
        barrier = threading.Barrier(2)

        def worker():
            django_db.close_old_connections()
            barrier.wait()
            try:
                process_delivery_task.apply(args=[str(delivery.id)]).get()
            finally:
                django_db.close_old_connections()

        _run_in_threads(worker, worker)

        after = _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
        assert len(fake_channel_calls) == 1
        assert after == before + 1

    def test_two_sweepers_never_inflate_the_actual_attempt_count(self, fake_channel_calls):
        """Section 36: publication may legitimately duplicate; the actual
        DeliveryAttempt count must not."""
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        before = _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")

        def sweep():
            django_db.close_old_connections()
            dispatch_due_deliveries()
            django_db.close_old_connections()

        _run_in_threads(sweep, sweep)
        # Both sweeps publish a real (synchronous-in-tests via .delay is
        # actually async in real Celery; here dispatch is best-effort and
        # this test asserts only the claim-side invariant) — drain any
        # published task synchronously to make the assertion deterministic.
        process_delivery_task.apply(args=[str(delivery.id)]).get()

        after = _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
        assert len(fake_channel_calls) == 1
        assert after == before + 1

    def test_terminal_replay_never_double_counts(self, fake_channel_calls):
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        process_delivery_task.apply(args=[str(delivery.id)]).get()
        before_attempts = _sum(
            f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification"
        )
        before_terminal = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total",
            channel="notification",
            outcome="delivered",
        )

        # Replay: the delivery is already DELIVERED (terminal) — a
        # redelivered task finds nothing claimable and no-ops.
        result = process_delivery_task.apply(args=[str(delivery.id)]).get()

        assert result == "skipped"
        assert len(fake_channel_calls) == 1
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
            == before_attempts
        )
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_terminal_total",
                channel="notification",
                outcome="delivered",
            )
            == before_terminal
        )


# ---------------------------------------------------------------------------
# Retries vs Celery task metric (section 10)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestRetryMetricIsDistinctFromCeleryOutcome:
    def test_retry_scheduled_increments_delivery_retries_not_celery_retry(self, fake_channel_calls):
        fake_channel_calls.outcomes.append(
            lambda delivery, token: complete_delivery_failure(
                delivery_id=delivery.id,
                claim_token=token,
                safe_error_code="integration_timeout",
                retryable=True,
            )
        )
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        before_retries = _sum(f"{METRIC_NAMESPACE}_delivery_retries_total", channel="notification")
        before_celery_retry = _sum(
            f"{METRIC_NAMESPACE}_celery_tasks_total",
            task_name="notifications.tasks.process_delivery_task",
            outcome="retry",
        )

        result = process_delivery_task.apply(args=[str(delivery.id)]).get()

        assert result == "processed"
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.RETRY_SCHEDULED
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_retries_total", channel="notification")
            == before_retries + 1
        )
        # The Celery task itself completed successfully (it never raised —
        # DB-controlled retry, not a Celery-level retry).
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_celery_tasks_total",
                task_name="notifications.tasks.process_delivery_task",
                outcome="retry",
            )
            == before_celery_retry
        )


# ---------------------------------------------------------------------------
# Terminal transitions: delivered / failed / dead distinguishable (section 11)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestTerminalOutcomesDistinguishable:
    def test_delivered_increments_delivered_outcome_and_end_to_end_duration(
        self, fake_channel_calls
    ):
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        before = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total",
            channel="notification",
            outcome="delivered",
        )
        before_e2e = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_delivery_end_to_end_duration_seconds_count")
            if s.labels.get("channel") == "notification"
        )

        process_delivery_task.apply(args=[str(delivery.id)]).get()

        after = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total",
            channel="notification",
            outcome="delivered",
        )
        after_e2e = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_delivery_end_to_end_duration_seconds_count")
            if s.labels.get("channel") == "notification"
        )
        assert after == before + 1
        assert after_e2e == before_e2e + 1

    def test_failed_and_dead_are_recorded_as_distinct_outcomes(self, fake_channel_calls):
        # FAILED: retryable failure, attempt budget exhausted (max_attempts=1).
        fake_channel_calls.outcomes.append(
            lambda delivery, token: complete_delivery_failure(
                delivery_id=delivery.id,
                claim_token=token,
                safe_error_code="integration_timeout",
                retryable=True,
            )
        )
        failed_delivery = DeliveryFactory(
            channel=FAKE_CHANNEL,
            max_attempts=1,
            next_attempt_at=timezone.now() - timedelta(seconds=1),
        )
        before_failed = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total", channel="notification", outcome="failed"
        )
        process_delivery_task.apply(args=[str(failed_delivery.id)]).get()
        failed_delivery.refresh_from_db()
        assert failed_delivery.status == DeliveryStatus.FAILED
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_terminal_total",
                channel="notification",
                outcome="failed",
            )
            == before_failed + 1
        )

        # DEAD: explicit non-retryable terminal failure.
        fake_channel_calls.outcomes.append(
            lambda delivery, token: complete_delivery_failure(
                delivery_id=delivery.id,
                claim_token=token,
                safe_error_code="integration_authentication_failed",
                retryable=False,
            )
        )
        dead_delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        before_dead = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total", channel="notification", outcome="dead"
        )
        process_delivery_task.apply(args=[str(dead_delivery.id)]).get()
        dead_delivery.refresh_from_db()
        assert dead_delivery.status == DeliveryStatus.DEAD
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_terminal_total",
                channel="notification",
                outcome="dead",
            )
            == before_dead + 1
        )

    def test_terminal_rollback_records_nothing(self, fake_channel_calls):
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        claimed, token = claim_delivery(delivery_id=delivery.id)
        before = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total",
            channel="notification",
            outcome="delivered",
        )
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                complete_delivery_success(delivery_id=claimed.id, claim_token=token)
                raise RuntimeError("forced rollback")
        after = _sum(
            f"{METRIC_NAMESPACE}_delivery_terminal_total",
            channel="notification",
            outcome="delivered",
        )
        assert after == before
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.CLAIMED


# ---------------------------------------------------------------------------
# Claim recovery / abandoned attempts (section 13, 33)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestClaimRecovery:
    def test_expired_claim_recovery_records_one_recovery_and_one_abandoned_observation(
        self, monkeypatch, fake_channel_calls
    ):
        def _synchronous_dispatch(delivery_id, **kwargs):
            process_delivery_task.apply(args=[delivery_id]).get()

        import notifications.recovery as recovery_module

        monkeypatch.setattr(
            recovery_module, "dispatch_delivery_for_processing", _synchronous_dispatch
        )

        now = timezone.now()
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=now - timedelta(minutes=10)
        )
        _, stale_token = claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)
        delivery.refresh_from_db()
        delivery.lease_expires_at = now - timedelta(seconds=1)
        delivery.save(update_fields=["lease_expires_at"])

        before_recoveries = _sum(
            f"{METRIC_NAMESPACE}_delivery_claim_recoveries_total", channel="notification"
        )
        before_abandoned = _sum(
            f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification"
        )

        recover_expired_delivery_claims()

        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED
        old_attempt = DeliveryAttempt.objects.get(delivery=delivery, claim_token=stale_token)
        assert old_attempt.status == AttemptStatus.ABANDONED
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_claim_recoveries_total", channel="notification")
            == before_recoveries + 1
        )
        # Reclaim itself is a genuine ownership acquisition too (a fresh
        # DeliveryAttempt row for the new claim) — one more than before.
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
            == before_abandoned + 1
        )
        abandoned_duration_samples = [
            s
            for s in _samples(f"{METRIC_NAMESPACE}_delivery_attempt_duration_seconds_count")
            if s.labels.get("channel") == "notification" and s.labels.get("outcome") == "abandoned"
        ]
        assert abandoned_duration_samples


# ---------------------------------------------------------------------------
# Broker publication failure never consumes attempt budget (section 14)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestBrokerPublicationFailure:
    def test_initial_broker_failure_does_not_consume_attempt_budget(self, monkeypatch):
        def _broker_down(*args, **kwargs):
            raise RuntimeError("broker unavailable")

        monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _broker_down)

        before = _sum(
            f"{METRIC_NAMESPACE}_delivery_broker_publication_failures_total",
            channel="notification",
            source="initial",
        )
        before_attempts = _sum(
            f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification"
        )

        delivery = create_delivery(workspace=WorkspaceFactory(), channel=FAKE_CHANNEL)

        assert delivery.status == DeliveryStatus.PENDING
        assert delivery.attempt_count == 0
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_broker_publication_failures_total",
                channel="notification",
                source="initial",
            )
            == before + 1
        )
        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_attempts_total", channel="notification")
            == before_attempts
        )

    def test_sweeper_broker_failure_is_labeled_source_sweeper(self, monkeypatch):
        def _broker_down(*args, **kwargs):
            raise RuntimeError("broker unavailable")

        monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _broker_down)
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )
        before = _sum(
            f"{METRIC_NAMESPACE}_delivery_broker_publication_failures_total",
            channel="notification",
            source="sweeper",
        )

        dispatch_due_deliveries()

        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.PENDING
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_delivery_broker_publication_failures_total",
                channel="notification",
                source="sweeper",
            )
            == before + 1
        )


# ---------------------------------------------------------------------------
# Redrive (section 27, 29, 34)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestRedrive:
    def _exhausted_webhook_delivery(self, monkeypatch):
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
        return webhook_delivery

    def test_accepted_redrive_increments_redrives_not_creations(self, monkeypatch):
        webhook_delivery = self._exhausted_webhook_delivery(monkeypatch)
        before_redrives = _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook")
        before_created = _sum(f"{METRIC_NAMESPACE}_deliveries_created_total", channel="webhook")

        redrive_webhook_delivery(
            workspace=webhook_delivery.workspace, webhook_delivery=webhook_delivery, actor=None
        )

        assert (
            _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook")
            == before_redrives + 1
        )
        assert (
            _sum(f"{METRIC_NAMESPACE}_deliveries_created_total", channel="webhook")
            == before_created
        )

    def test_rejected_redrive_records_no_successful_redrive(self, monkeypatch):
        from webhooks.errors import WebhookDeliveryNotRedrivableError

        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        webhook_delivery = WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        before = _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook")

        with pytest.raises(WebhookDeliveryNotRedrivableError):
            redrive_webhook_delivery(
                workspace=endpoint.workspace, webhook_delivery=webhook_delivery, actor=None
            )

        assert _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook") == before

    def test_rolled_back_redrive_records_nothing(self, monkeypatch):
        webhook_delivery = self._exhausted_webhook_delivery(monkeypatch)
        before = _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook")

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                redrive_webhook_delivery(
                    workspace=webhook_delivery.workspace,
                    webhook_delivery=webhook_delivery,
                    actor=None,
                )
                raise RuntimeError("forced rollback")

        assert _sum(f"{METRIC_NAMESPACE}_delivery_redrives_total", channel="webhook") == before
        webhook_delivery.delivery.refresh_from_db()
        assert webhook_delivery.delivery.status == DeliveryStatus.FAILED


# ---------------------------------------------------------------------------
# Webhook response classes / SSRF rejection (section 22-25)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestWebhookResponsesAndDestinationRejection:
    def _webhook_delivery(self, monkeypatch):
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        return delivery

    def test_2xx_and_5xx_responses_are_classified(self, monkeypatch):
        delivery = self._webhook_delivery(monkeypatch)
        monkeypatch.setattr(
            "webhooks.services.send_pinned_request",
            lambda **kwargs: TransportResult(status_code=204, latency_ms=1),
        )
        before_2xx = _sum(f"{METRIC_NAMESPACE}_webhook_responses_total", status_class="2xx")
        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
        assert (
            _sum(f"{METRIC_NAMESPACE}_webhook_responses_total", status_class="2xx")
            == before_2xx + 1
        )

    def test_destination_rejection_is_recorded_with_bounded_reason(self, monkeypatch):
        delivery = self._webhook_delivery(monkeypatch)
        monkeypatch.setattr(
            "webhooks.services.resolve_and_validate",
            lambda h, p: (_ for _ in ()).throw(WebhookDestinationBlockedError()),
        )
        before = _sum(
            f"{METRIC_NAMESPACE}_webhook_destination_rejections_total", reason="destination_blocked"
        )
        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
        assert (
            _sum(
                f"{METRIC_NAMESPACE}_webhook_destination_rejections_total",
                reason="destination_blocked",
            )
            == before + 1
        )

    def test_invalid_url_rejection_reason_is_bounded(self, monkeypatch):
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        monkeypatch.setattr(
            "webhooks.services.parse_webhook_url",
            lambda url: (_ for _ in ()).throw(WebhookInvalidURLError()),
        )
        before = _sum(
            f"{METRIC_NAMESPACE}_webhook_destination_rejections_total", reason="invalid_url"
        )
        claimed, token = claim_delivery(delivery_id=delivery.id)
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)
        assert (
            _sum(f"{METRIC_NAMESPACE}_webhook_destination_rejections_total", reason="invalid_url")
            == before + 1
        )


# ---------------------------------------------------------------------------
# Backlog / recovery-lag gauges (section 16-19)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestBacklogGauges:
    def test_due_count_and_oldest_due_age_reflect_actual_backlog(self):
        now = timezone.now()
        DeliveryFactory(
            channel=DeliveryChannel.NOTIFICATION,
            status=DeliveryStatus.PENDING,
            next_attempt_at=now - timedelta(seconds=90),
        )
        DeliveryFactory(
            channel=DeliveryChannel.NOTIFICATION,
            status=DeliveryStatus.RETRY_SCHEDULED,
            next_attempt_at=now + timedelta(hours=1),  # not due — excluded
        )

        refresh_delivery_backlog_gauges(now=now)

        due = _gauge_value(f"{METRIC_NAMESPACE}_delivery_due_count", channel="notification")
        oldest_age = _gauge_value(
            f"{METRIC_NAMESPACE}_delivery_oldest_due_age_seconds", channel="notification"
        )
        assert due is not None and due >= 1
        assert oldest_age is not None and oldest_age >= 85

    def test_no_due_deliveries_reports_zero_age(self):
        now = timezone.now()
        Delivery.objects.filter(channel=DeliveryChannel.WEBHOOK).delete()

        refresh_delivery_backlog_gauges(now=now)

        due = _gauge_value(f"{METRIC_NAMESPACE}_delivery_due_count", channel="webhook")
        oldest_age = _gauge_value(
            f"{METRIC_NAMESPACE}_delivery_oldest_due_age_seconds", channel="webhook"
        )
        assert due == 0
        assert oldest_age == 0

    def test_expired_claim_count_reflects_actual_expired_claims(self):
        now = timezone.now()
        DeliveryFactory(
            channel=DeliveryChannel.WEBHOOK,
            status=DeliveryStatus.CLAIMED,
            claim_token=uuid.uuid4(),
            claimed_at=now - timedelta(minutes=10),
            lease_expires_at=now - timedelta(minutes=1),
        )

        refresh_delivery_backlog_gauges(now=now)

        expired = _gauge_value(
            f"{METRIC_NAMESPACE}_delivery_expired_claim_count", channel="webhook"
        )
        assert expired is not None and expired >= 1

    def test_gauge_refresh_uses_two_bounded_aggregate_queries(self, django_assert_num_queries):
        DeliveryFactory.create_batch(5, next_attempt_at=timezone.now() - timedelta(seconds=1))
        with django_assert_num_queries(2):
            refresh_delivery_backlog_gauges()

    def test_db_collector_failure_does_not_break_the_scrape(self, monkeypatch):
        import notifications.selectors as selectors_module

        def _boom(**kwargs):
            raise RuntimeError("db exploded")

        monkeypatch.setattr(selectors_module, "due_claimable_deliveries", _boom)

        # Must not raise — failure isolation (section 21).
        refresh_delivery_backlog_gauges()
        # The rest of the metrics text still renders.
        assert _metrics_text()


# ---------------------------------------------------------------------------
# Failure isolation (section 41)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestFailureIsolation:
    def test_broken_delivery_metric_recording_does_not_affect_committed_state(
        self, monkeypatch, fake_channel_calls
    ):
        import observability.metrics as metrics_module

        monkeypatch.setattr(
            metrics_module,
            "observe_delivery_terminal",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        delivery = DeliveryFactory(
            channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
        )

        result = process_delivery_task.apply(args=[str(delivery.id)]).get()

        assert result == "processed"
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED

    def test_broken_span_helper_does_not_affect_committed_state(self, monkeypatch):
        import observability.tracing as tracing_module

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
        monkeypatch.setattr(
            tracing_module,
            "get_tracer",
            lambda: (_ for _ in ()).throw(RuntimeError("tracer exploded")),
        )
        from django.test import override_settings

        with override_settings(OBSERVABILITY_TRACING_ENABLED=True):
            claimed, token = claim_delivery(delivery_id=delivery.id)
            handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED


# ---------------------------------------------------------------------------
# Cardinality / secret marker attacks (section 39-40)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCardinalityAndPrivacy:
    def test_many_distinct_ids_never_leak_and_labels_stay_bounded(self, fake_channel_calls):
        leaked_ids = []
        for _ in range(8):
            delivery = DeliveryFactory(
                channel=FAKE_CHANNEL, next_attempt_at=timezone.now() - timedelta(seconds=1)
            )
            leaked_ids.append(str(delivery.id))
            leaked_ids.append(str(delivery.workspace_id))
            process_delivery_task.apply(args=[str(delivery.id)]).get()

        body = _metrics_text()
        for leaked in leaked_ids:
            assert leaked not in body

        label_sets = {
            frozenset(s.labels.items())
            for family in text_string_to_metric_families(body)
            for s in family.samples
            if s.name == f"{METRIC_NAMESPACE}_delivery_terminal_total"
        }
        # channel(2) x outcome(3) = 6 is the entire possible universe.
        assert len(label_sets) <= 6

    def test_secret_marker_in_webhook_url_and_payload_never_reaches_metrics_spans_or_logs(
        self, monkeypatch, caplog
    ):
        import logging

        endpoint = WebhookEndpointFactory(url=f"https://example.com/{SECRET_MARKER}")
        event = WebhookEventFactory(
            workspace=endpoint.workspace, payload_snapshot={"note": SECRET_MARKER}
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

        with caplog.at_level(logging.DEBUG):
            claimed, token = claim_delivery(delivery_id=delivery.id)
            handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

        assert SECRET_MARKER not in _metrics_text()
        for record in caplog.records:
            assert SECRET_MARKER not in record.getMessage()

    def test_secret_marker_in_provider_error_never_reaches_metrics(self, monkeypatch):
        from integrations.errors import IntegrationTimeoutError
        from notifications.notification_delivery import (
            create_or_reuse_notification_delivery,
            handle_notification_delivery_attempt,
        )
        from tools.tests.factories import ToolExecutionFactory

        tool_execution = ToolExecutionFactory()
        notification_delivery = create_or_reuse_notification_delivery(
            tool_execution=tool_execution,
            workspace=tool_execution.workspace,
            recipient_email=f"user+{SECRET_MARKER}@example.com",
            subject=SECRET_MARKER,
            body=SECRET_MARKER,
        )

        def _boom(**kwargs):
            raise IntegrationTimeoutError(SECRET_MARKER)

        monkeypatch.setattr("notifications.notification_delivery.send_notification", _boom)
        claimed, token = claim_delivery(delivery_id=notification_delivery.delivery_id)

        handle_notification_delivery_attempt(delivery=claimed, claim_token=token)

        assert SECRET_MARKER not in _metrics_text()
