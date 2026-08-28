"""HTTP metrics middleware tests (Phase 11 Block 1, sections 10-11, 46-47)."""

from __future__ import annotations

import uuid

import pytest
from prometheus_client.parser import text_string_to_metric_families
from rest_framework.test import APIClient

from observability.metrics import METRIC_NAMESPACE, render_metrics


@pytest.fixture
def api_client():
    return APIClient()


def _all_route_labels(metric_name: str) -> set[str]:
    body = render_metrics().decode("utf-8")
    routes = set()
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            if sample.name == metric_name and "route" in sample.labels:
                routes.add(sample.labels["route"])
    return routes


def _method_labels_for_route(metric_name: str, route: str) -> set[str]:
    body = render_metrics().decode("utf-8")
    return {
        sample.labels["method"]
        for family in text_string_to_metric_families(body)
        for sample in family.samples
        if sample.name == metric_name
        and sample.labels.get("route") == route
        and "method" in sample.labels
    }


@pytest.mark.django_db
class TestMetricsMiddlewareRouteNormalization:
    def test_known_route_uses_the_bounded_url_name_not_the_raw_path(self, api_client):
        api_client.get("/health/")

        routes = _all_route_labels(f"{METRIC_NAMESPACE}_http_requests_total")
        assert "health:health" in routes

    def test_unmatched_path_collapses_to_a_single_bounded_route_label(self, api_client):
        for _ in range(5):
            api_client.get(f"/api/v1/does-not-exist/{uuid.uuid4()}/")

        routes = _all_route_labels(f"{METRIC_NAMESPACE}_http_requests_total")
        assert "unmatched" in routes

    def test_cardinality_attack_many_distinct_probed_paths_stay_one_series(self, api_client):
        """A real release-blocking property (section 47): an attacker
        path-scanning many distinct URLs must never create one metric time
        series per attempted path."""
        probed_paths = [f"/api/v1/{uuid.uuid4()}/{uuid.uuid4()}/" for _ in range(50)]
        for path in probed_paths:
            api_client.get(path)

        body = render_metrics().decode("utf-8")
        # None of the randomly generated UUIDs used as probe paths may
        # appear anywhere in the exposed metrics text.
        for path in probed_paths:
            assert path not in body

        routes = _all_route_labels(f"{METRIC_NAMESPACE}_http_requests_total")
        assert "unmatched" in routes
        # The 50 distinct probed paths collapsed into exactly one bucket —
        # never one series per attempted path.
        value = None
        body = render_metrics().decode("utf-8")
        for family in text_string_to_metric_families(body):
            for sample in family.samples:
                if (
                    sample.name == f"{METRIC_NAMESPACE}_http_requests_total"
                    and sample.labels.get("route") == "unmatched"
                ):
                    value = (value or 0.0) + sample.value
        assert value is not None and value >= 50


@pytest.mark.django_db
class TestMetricsMiddlewareMethodNormalization:
    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
    def test_normal_methods_retain_their_own_bounded_label(self, api_client, method):
        api_client.generic(method, "/health/")

        methods = _method_labels_for_route(
            f"{METRIC_NAMESPACE}_http_requests_total", "health:health"
        )
        assert method in methods

    def test_cardinality_attack_custom_methods_collapse_to_one_series(self, api_client):
        custom_methods = [f"CUSTOM_{index:04d}" for index in range(1, 101)]
        for method in custom_methods:
            api_client.generic(method, "/health/")

        body = render_metrics().decode("utf-8")
        for method in custom_methods:
            assert method not in body

        counter_methods = _method_labels_for_route(
            f"{METRIC_NAMESPACE}_http_requests_total", "health:health"
        )
        histogram_methods = _method_labels_for_route(
            f"{METRIC_NAMESPACE}_http_request_duration_seconds_count", "health:health"
        )
        assert "OTHER" in counter_methods
        assert "OTHER" in histogram_methods
        assert not counter_methods.intersection(custom_methods)
        assert not histogram_methods.intersection(custom_methods)


@pytest.mark.django_db
class TestMetricsMiddlewareExclusions:
    def test_metrics_endpoint_itself_is_excluded_from_http_request_metrics(self, api_client):
        api_client.get("/metrics/")  # denied (no token) but still must not self-count

        routes = _all_route_labels(f"{METRIC_NAMESPACE}_http_requests_total")
        assert "metrics" not in routes


@pytest.mark.django_db
class TestMetricsMiddlewareFailureIsolation:
    def test_metrics_recording_failure_does_not_break_the_response(self, api_client, monkeypatch):
        def _boom(**kwargs):
            raise RuntimeError("telemetry backend exploded")

        monkeypatch.setattr("observability.middleware.observe_http_request", _boom)

        response = api_client.get("/health/")

        assert response.status_code == 200
        assert response.data == {"status": "healthy"}
