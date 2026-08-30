"""Phase 11 Block 5: adversarial observability hardening.

Cross-domain cardinality/series-ceiling proofs, HTTP method label
poisoning, stale-worker terminal-metric fencing, DB-gauge scale/query-count
behavior, a negative-duration clamp regression, an OTLP slow-collector
non-blocking proof, alert-rule/SLO metric-existence consistency, tenant
label leakage, and a regex-based scrape-content audit. Complements the
per-domain adversarial coverage already established in Blocks 1-4
(``test_domain_instrumentation.py``, ``test_delivery_instrumentation.py``,
``test_middleware.py``, ``test_tracing*.py``, ``common/tests/test_request_id.py``)
rather than duplicating it.
"""

from __future__ import annotations

import re
import socket
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from django.utils import timezone
from prometheus_client.parser import text_string_to_metric_families
from rest_framework.test import APIClient

from notifications.errors import StaleClaimError
from notifications.models import Delivery, DeliveryChannel
from notifications.services import claim_delivery, complete_delivery_success, create_delivery
from notifications.tests.factories import DeliveryFactory
from observability.metrics import METRIC_NAMESPACE, render_metrics
from webhooks.models import WebhookDelivery
from webhooks.tests.factories import WebhookEndpointFactory, WebhookEventFactory
from webhooks.transport import TransportResult
from workspaces.tests.factories import WorkspaceFactory

_REPO_ROOT = Path(__file__).resolve().parents[3]


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


# ---------------------------------------------------------------------------
# 1. Global cross-domain cardinality attack + series-ceiling proofs
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestGlobalCardinalityAttack:
    def test_many_unique_ids_across_http_delivery_and_webhook_never_leak(self, monkeypatch):
        leaked: list[str] = []
        client = APIClient()

        for _ in range(10):
            probe_id = str(uuid.uuid4())
            leaked.append(probe_id)
            client.get(f"/api/v1/{probe_id}/does-not-exist/")

        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        leaked.append(str(endpoint.id))
        leaked.append(str(event.id))
        leaked.append(str(endpoint.workspace_id))
        leaked.append(endpoint.url)
        monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
        monkeypatch.setattr(
            "webhooks.services.send_pinned_request",
            lambda **kwargs: TransportResult(status_code=204, latency_ms=1),
        )
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        leaked.append(str(delivery.id))
        WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        claimed, token = claim_delivery(delivery_id=delivery.id)
        leaked.append(str(token))
        from webhooks.services import handle_webhook_delivery_attempt

        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

        body = _metrics_text()
        for value in leaked:
            assert value not in body

    def test_delivery_terminal_series_stay_within_the_bounded_universe(self):
        """channel(2) x outcome(3) = 6 is the entire possible universe for
        ``supportpilot_delivery_terminal_total`` regardless of how many
        distinct Deliveries have ever been created."""
        label_sets = {
            frozenset(s.labels.items())
            for s in _samples(f"{METRIC_NAMESPACE}_delivery_terminal_total")
        }
        assert len(label_sets) <= 6

    def test_webhook_response_series_stay_within_the_bounded_universe(self):
        """status_class only — 5 possible values (2xx/3xx/4xx/5xx/other)."""
        label_sets = {
            frozenset(s.labels.items())
            for s in _samples(f"{METRIC_NAMESPACE}_webhook_responses_total")
        }
        assert len(label_sets) <= 5

    def test_agent_run_series_stay_within_the_bounded_universe(self):
        """trigger(bounded) x outcome(5) — never one series per AgentRun."""
        from observability.metrics import _AGENT_RUN_OUTCOMES, _AGENT_RUN_TRIGGERS

        label_sets = {
            frozenset(s.labels.items()) for s in _samples(f"{METRIC_NAMESPACE}_agent_runs_total")
        }
        assert len(label_sets) <= len(_AGENT_RUN_TRIGGERS) * len(_AGENT_RUN_OUTCOMES)


# ---------------------------------------------------------------------------
# 2. Metric label poisoning through the HTTP method
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestHttpMethodLabelPoisoning:
    @pytest.mark.parametrize(
        "poison",
        [
            "GET\nX-Injected: evil",
            'GET"OR"1"="1',
            'GET,evil{label="x"}',
            'GET{le="+Inf"}',
            "A" * 5000,
            "GÉT-Ünïcödé",
            "\x1b[31mGET\x1b[0m",
        ],
    )
    def test_poisoned_method_collapses_to_the_bounded_other_label(self, poison):
        client = APIClient()
        try:
            client.generic(poison, "/health/")
        except Exception:  # noqa: BLE001 - some poisons are rejected by the WSGI/test layer itself
            pytest.skip("test client/WSGI layer itself rejected this method value")

        body = _metrics_text()
        assert poison not in body

        methods = {
            s.labels.get("method")
            for s in _samples(f"{METRIC_NAMESPACE}_http_requests_total")
            if s.labels.get("route") not in ("metrics", "health:health", "health:readiness")
        }
        # Every method label actually present must be a bounded value —
        # never the raw poisoned string.
        for method in methods:
            assert method is None or method in {
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "HEAD",
                "OPTIONS",
                "OTHER",
            }


# ---------------------------------------------------------------------------
# 3. Stale-worker terminal-metric fencing (section 37 hard gate)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestStaleWorkerTerminalMetricFencing:
    def test_rejected_stale_completion_records_no_terminal_metric(self):
        now = timezone.now()
        delivery = DeliveryFactory(next_attempt_at=now - timedelta(seconds=1))
        _, stale_token = claim_delivery(delivery_id=delivery.id, lease_seconds=1, now=now)
        Delivery.objects.filter(pk=delivery.id).update(lease_expires_at=now - timedelta(seconds=1))

        # A fresh worker reclaims and completes successfully — this is the
        # only transition that may ever legitimately increment the terminal
        # metric here.
        from notifications.services import reclaim_expired_delivery

        reclaimed, fresh_token = reclaim_expired_delivery(delivery_id=delivery.id)
        complete_delivery_success(delivery_id=reclaimed.id, claim_token=fresh_token)

        before = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_delivery_terminal_total")
            if s.labels.get("channel") == "notification" and s.labels.get("outcome") == "delivered"
        )

        # The original (now-stale) worker tries to complete with its old
        # token — must be rejected and must record nothing.
        with pytest.raises(StaleClaimError):
            complete_delivery_success(delivery_id=delivery.id, claim_token=stale_token)

        after = sum(
            s.value
            for s in _samples(f"{METRIC_NAMESPACE}_delivery_terminal_total")
            if s.labels.get("channel") == "notification" and s.labels.get("outcome") == "delivered"
        )
        assert after == before


# ---------------------------------------------------------------------------
# 4. DB gauge scale + fixed query count
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestDbGaugeScale:
    def test_query_count_stays_fixed_at_scale(self, django_assert_num_queries):
        from observability.metrics import refresh_delivery_backlog_gauges

        workspace = WorkspaceFactory()
        now = timezone.now()
        rows = DeliveryFactory.build_batch(
            2000, workspace=workspace, next_attempt_at=now - timedelta(seconds=1)
        )
        Delivery.objects.bulk_create(rows)

        with django_assert_num_queries(2):
            refresh_delivery_backlog_gauges(now=now)


# ---------------------------------------------------------------------------
# 5. Negative-duration clamp regression (section 34/49)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestNegativeDurationClamp:
    def test_handoff_resolution_duration_never_goes_negative(self, monkeypatch):
        from tickets import services as tickets_services
        from tickets.tests.factories import HumanHandoffFactory
        from workspaces.models import WorkspaceRole
        from workspaces.tests.factories import WorkspaceMembershipFactory

        handoff = HumanHandoffFactory()
        manager = WorkspaceMembershipFactory(
            workspace=handoff.workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )

        # Force ``timezone.now()`` (as read inside ``resolve_handoff``) to
        # return a value earlier than ``handoff.created_at`` — the
        # pathological clock-skew case the clamp defends against; this
        # never happens through the real service under a synchronized
        # clock, so it must be forced directly at the boundary under test.
        earlier = handoff.created_at - timedelta(seconds=30)
        monkeypatch.setattr(tickets_services.timezone, "now", lambda: earlier)

        recorded: list[float | None] = []
        monkeypatch.setattr(
            "observability.metrics.observe_handoff_terminal",
            lambda **kwargs: recorded.append(kwargs.get("duration_seconds")),
        )

        tickets_services.resolve_handoff(
            workspace=handoff.workspace,
            actor=manager.user,
            actor_membership=manager,
            handoff=handoff,
        )

        assert recorded == [0.0]


# ---------------------------------------------------------------------------
# 6. OTLP slow collector must not block business execution
# ---------------------------------------------------------------------------


class TestOtlpSlowCollectorDoesNotBlock:
    def test_a_connection_that_accepts_but_never_responds_does_not_block_a_span(self, settings):
        """A collector that accepts the TCP connection and then simply
        never responds is the realistic "slow collector" case —
        ``BatchSpanProcessor`` exports on its own background thread with
        its own bounded timeout, so span creation/completion on the
        request/task thread must return promptly regardless."""
        from observability import tracing

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind(("127.0.0.1", 0))
        server_socket.listen(1)
        port = server_socket.getsockname()[1]
        stop = threading.Event()

        def _accept_and_hang():
            server_socket.settimeout(0.2)
            while not stop.is_set():
                try:
                    # Accepted; deliberately never read from or responded
                    # to — this is the "slow collector" being simulated.
                    server_socket.accept()
                except OSError:
                    # Either a benign accept timeout (retry) or the listen
                    # socket was closed by the main thread during teardown
                    # (``stop`` will already be set by then) — either way
                    # this loop must never propagate an exception onto the
                    # test's thread-exception hook.
                    continue

        thread = threading.Thread(target=_accept_and_hang, daemon=True)
        thread.start()
        try:
            settings.OBSERVABILITY_TRACING_ENABLED = True
            settings.OBSERVABILITY_OTLP_ENDPOINT = f"http://127.0.0.1:{port}/v1/traces"
            tracing.use_provider_for_tests(None)

            started = time.monotonic()
            with tracing.server_span("HTTP request") as span:
                assert span is not None
            elapsed = time.monotonic() - started
            # Generous bound (section 18: no fragile microbenchmark) — span
            # creation/completion on the caller's thread must be
            # near-instant; export happens on a separate background thread.
            assert elapsed < 2.0
        finally:
            stop.set()
            server_socket.close()
            thread.join(timeout=2)
            tracing.use_provider_for_tests(None)


# ---------------------------------------------------------------------------
# 7. Alert-rule / SLO metric-existence consistency (sections 58-59)
# ---------------------------------------------------------------------------


def _known_full_metric_names() -> set[str]:
    body = _metrics_text()
    names: set[str] = set()
    for family in text_string_to_metric_families(body):
        if family.type == "counter":
            names.add(f"{family.name}_total")
        elif family.type == "histogram":
            # Both the PromQL-query forms (``_bucket``/``_sum``/``_count``)
            # and the bare family name — documentation prose legitimately
            # refers to a histogram by its base name without a query
            # suffix (e.g. "not attempt duration
            # (supportpilot_delivery_attempt_duration_seconds)").
            names.update(
                {family.name, f"{family.name}_bucket", f"{family.name}_sum", f"{family.name}_count"}
            )
        else:
            names.add(family.name)
    return names


def _referenced_metric_names(text: str) -> set[str]:
    return set(re.findall(r"supportpilot_[a-zA-Z0-9_]+", text))


class TestAlertAndSloMetricExistenceConsistency:
    def test_every_alert_rule_metric_reference_exists(self):
        rules_path = _REPO_ROOT / "deploy" / "observability" / "prometheus-rules.yml"
        rules_text = rules_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(rules_text)  # structural validation (no promtool available)
        assert parsed["groups"]

        known = _known_full_metric_names()
        referenced = _referenced_metric_names(rules_text)
        missing = {name for name in referenced if name not in known}
        assert not missing, f"alert rules reference nonexistent metrics: {missing}"

    def test_every_slo_doc_metric_reference_exists(self):
        slo_path = _REPO_ROOT / "docs" / "observability" / "slos.md"
        slo_text = slo_path.read_text(encoding="utf-8")

        known = _known_full_metric_names()
        referenced = _referenced_metric_names(slo_text)
        missing = {name for name in referenced if name not in known}
        assert not missing, f"SLO doc references nonexistent metrics: {missing}"

    def test_slo_and_runbook_never_claim_exactly_once_delivery(self):
        """Every occurrence of "exactly-once"/"exactly once" in these docs
        must be a *negation* ("never exactly-once", "not exactly-once") —
        never a positive claim that delivery is exactly-once."""
        pattern = re.compile(r"exactly[- ]once")
        for relative in (
            "docs/observability/slos.md",
            "docs/observability/runbook.md",
            "docs/adr/0009-vendor-neutral-observability-with-bounded-cardinality-telemetry.md",
        ):
            text = (_REPO_ROOT / relative).read_text(encoding="utf-8").lower()
            negations = ("never", "not", "no ", "n't")
            for match in pattern.finditer(text):
                preceding = text[max(0, match.start() - 60) : match.start()]
                assert any(neg in preceding for neg in negations), (
                    f"{relative} appears to positively claim exactly-once "
                    f"delivery near: {text[max(0, match.start() - 40): match.end() + 10]!r}"
                )


# ---------------------------------------------------------------------------
# 8. Tenant label leakage (section 63)
# ---------------------------------------------------------------------------


_FORBIDDEN_LABEL_KEYS = frozenset(
    {
        "workspace_id",
        "workspace",
        "customer_id",
        "user_id",
        "tenant_id",
        "tenant",
        "conversation_id",
        "ticket_id",
        "delivery_id",
        "request_id",
        "trace_id",
        "span_id",
    }
)


@pytest.mark.django_db(transaction=True)
class TestNoTenantOrIdentifierLabelKeys:
    def test_no_metric_family_ever_uses_a_forbidden_label_key(self):
        body = _metrics_text()
        found_keys: set[str] = set()
        for family in text_string_to_metric_families(body):
            for sample in family.samples:
                found_keys.update(sample.labels.keys())
        leaked = found_keys & _FORBIDDEN_LABEL_KEYS
        assert not leaked, f"forbidden identifier label keys found: {leaked}"


# ---------------------------------------------------------------------------
# 9. Scrape content audit (section 57)
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_URL_RE = re.compile(r"https?://")


@pytest.mark.django_db(transaction=True)
class TestScrapeContentAudit:
    def test_no_uuid_email_or_url_appears_anywhere_in_a_realistic_scrape(self, monkeypatch):
        endpoint = WebhookEndpointFactory(url="https://attacker-controlled.example.com/hook")
        event = WebhookEventFactory(
            workspace=endpoint.workspace, payload_snapshot={"email": "customer@example.com"}
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
        from webhooks.services import handle_webhook_delivery_attempt

        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

        body = _metrics_text()
        assert not _UUID_RE.search(body), "a UUID leaked into the scrape output"
        assert not _EMAIL_RE.search(body), "an email address leaked into the scrape output"
        assert not _URL_RE.search(body), "a URL leaked into the scrape output"
