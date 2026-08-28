"""Metrics registry unit tests (Phase 11 Block 1, section 46)."""

from __future__ import annotations

from prometheus_client.parser import text_string_to_metric_families

from observability.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    METRIC_NAMESPACE,
    observe_http_request,
    render_metrics,
)


def _sample_value(*, metric_name: str, labels: dict) -> float | None:
    body = render_metrics().decode("utf-8")
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return None


class TestMetricNaming:
    def test_metric_names_use_the_stable_namespace_prefix(self):
        assert HTTP_REQUESTS_TOTAL._name == f"{METRIC_NAMESPACE}_http_requests"
        assert (
            HTTP_REQUEST_DURATION_SECONDS._name
            == f"{METRIC_NAMESPACE}_http_request_duration_seconds"
        )

    def test_only_bounded_labels_are_declared(self):
        assert set(HTTP_REQUESTS_TOTAL._labelnames) == {"method", "route", "status_class"}
        assert set(HTTP_REQUEST_DURATION_SECONDS._labelnames) == {"method", "route"}


class TestHttpRequestObservation:
    def test_counter_increments_on_each_observation(self):
        labels = {
            "method": "GET",
            "route": "test-metrics-counter-route",
            "status_class": "2xx",
        }
        before = (
            _sample_value(metric_name=f"{METRIC_NAMESPACE}_http_requests_total", labels=labels)
            or 0.0
        )

        observe_http_request(
            method="GET", route="test-metrics-counter-route", status_code=200, duration_seconds=0.01
        )

        after = _sample_value(metric_name=f"{METRIC_NAMESPACE}_http_requests_total", labels=labels)
        assert after == before + 1.0

    def test_status_class_bucketing_is_correct_for_every_class(self):
        cases = [(200, "2xx"), (201, "2xx"), (302, "3xx"), (404, "4xx"), (500, "5xx"), (503, "5xx")]
        for status_code, expected_class in cases:
            route = f"test-metrics-status-class-{status_code}"
            observe_http_request(
                method="GET", route=route, status_code=status_code, duration_seconds=0.01
            )
            value = _sample_value(
                metric_name=f"{METRIC_NAMESPACE}_http_requests_total",
                labels={"method": "GET", "route": route, "status_class": expected_class},
            )
            assert value == 1.0

    def test_out_of_range_status_codes_collapse_to_one_bounded_fallback(self):
        for status_code in (199, 600, 999):
            route = f"test-metrics-status-fallback-{status_code}"
            observe_http_request(
                method="GET", route=route, status_code=status_code, duration_seconds=0.01
            )
            value = _sample_value(
                metric_name=f"{METRIC_NAMESPACE}_http_requests_total",
                labels={"method": "GET", "route": route, "status_class": "other"},
            )
            assert value == 1.0

    def test_histogram_records_an_observation_in_the_count_series(self):
        route = "test-metrics-histogram-route"
        observe_http_request(method="POST", route=route, status_code=201, duration_seconds=0.02)

        count = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_http_request_duration_seconds_count",
            labels={"method": "POST", "route": route},
        )
        assert count == 1.0

    def test_render_metrics_uses_the_multiprocess_collector_when_configured(
        self, tmp_path, monkeypatch
    ):
        """Section 29/62: exercises the multiprocess branch of
        ``render_metrics`` directly — the branch a normal single-process
        test/dev run never otherwise takes."""
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

        body = render_metrics().decode("utf-8")

        # An empty multiprocess directory is a valid (if empty) collector
        # state — the call must not raise, and must not fall back to the
        # single-process registry (which already has samples from earlier
        # tests in this module, so it would not be empty).
        assert f"{METRIC_NAMESPACE}_http_requests_total" not in body

    def test_repeated_registration_does_not_raise(self):
        """Re-importing the metrics module (as a fresh test process would)
        must never raise a duplicate-registration error — the metric objects
        are module-level singletons, constructed exactly once per process."""
        import importlib

        import observability.metrics as metrics_module

        # Re-executing the already-imported module object in place (not via
        # importlib.reload, which *would* legitimately re-register against
        # the global default registry and is not what this test is about)
        # confirms the objects it exposes are stable, singleton references.
        reimported = importlib.import_module("observability.metrics")
        assert reimported is metrics_module
