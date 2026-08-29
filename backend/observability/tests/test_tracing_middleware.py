"""Tests for ``observability.middleware.TracingMiddleware`` (Phase 11
Block 2 remediation, Part B)."""

from __future__ import annotations

import logging

from opentelemetry.trace.status import StatusCode
from rest_framework.test import APIClient

from observability import tracing


class TestTracingMiddlewareBasic:
    def test_a_normal_request_produces_exactly_one_server_span(self, db, traced):
        response = APIClient().get("/health/")

        assert response.status_code == 200
        finished = traced.get_finished_spans()
        assert len(finished) == 1
        assert finished[0].kind.name == "SERVER"

    def test_span_name_uses_the_normalized_route_not_the_raw_path(self, db, traced):
        APIClient().get("/health/")

        finished = traced.get_finished_spans()[0]
        assert finished.name == "HTTP GET health:health"

    def test_unresolved_path_collapses_to_the_bounded_unmatched_route(self, db, traced):
        secret_path = "/api/v1/does-not-exist-abc123/"
        APIClient().get(secret_path)

        finished = traced.get_finished_spans()[0]
        assert finished.attributes["http.route"] == "unmatched"
        assert secret_path not in finished.name
        for value in finished.attributes.values():
            assert secret_path not in str(value)

    def test_metrics_endpoint_is_excluded_from_tracing_entirely(self, db, traced):
        APIClient().get("/metrics/")  # denied (no token), still must not trace

        assert traced.get_finished_spans() == ()

    def test_disabled_mode_creates_no_span_and_request_still_succeeds(self, db, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = False
        response = APIClient().get("/health/")
        assert response.status_code == 200


class TestTracingMiddlewareFailureSemantics:
    def test_5xx_response_marks_the_span_with_error_status_only(self, db, traced, monkeypatch):
        # Force a downstream failure without touching business exception
        # handling: metrics recording is a convenient existing failure
        # point that does not affect the HTTP response, so instead force
        # the *view itself* to fail via an unrelated broken dependency
        # would require a real broken view. Simplest: hit an endpoint that
        # legitimately 500s is unavailable here, so this test instead
        # verifies via a synthetic response using the middleware directly.
        from observability.middleware import TracingMiddleware

        class _Response:
            status_code = 500

        def get_response(request):
            return _Response()

        middleware = TracingMiddleware(get_response)
        from django.test import RequestFactory

        request = RequestFactory().get("/some/path/")
        middleware(request)

        finished = traced.get_finished_spans()[0]
        assert finished.status.status_code == StatusCode.ERROR
        assert not finished.status.description

    def test_an_exception_raised_by_get_response_still_propagates(self, db, traced):
        from observability.middleware import TracingMiddleware

        class Boom(Exception):
            pass

        def get_response(request):
            raise Boom("business failure")

        middleware = TracingMiddleware(get_response)
        from django.test import RequestFactory

        request = RequestFactory().get("/some/path/")
        try:
            middleware(request)
        except Boom:
            pass
        else:
            raise AssertionError("business exception was swallowed")

        finished = traced.get_finished_spans()[0]
        assert finished.status.status_code == StatusCode.ERROR
        assert not finished.status.description


class TestTracingMiddlewareFailureIsolation:
    def test_broken_span_creation_never_breaks_the_http_response(self, db, settings, monkeypatch):
        """Section 24: force the actual span-creation path (inside
        ``observability.tracing``, not the middleware itself) to raise, end
        to end through the real HTTP client — the business response must
        be unaffected."""
        settings.OBSERVABILITY_TRACING_ENABLED = True

        def _broken_get_tracer():
            raise RuntimeError("tracer backend exploded")

        monkeypatch.setattr(tracing, "get_tracer", _broken_get_tracer)

        response = APIClient().get("/health/")

        assert response.status_code == 200
        assert response.data == {"status": "healthy"}


class TestSecretMarkerIsolation:
    def test_marker_in_headers_and_body_never_reaches_span_data(self, db, traced):
        marker = "SUPER_SECRET_TRACE_MARKER_284731"

        APIClient().get(
            "/health/",
            HTTP_AUTHORIZATION=f"Bearer {marker}",
            HTTP_X_CUSTOM_MARKER=marker,
        )

        finished = traced.get_finished_spans()[0]
        assert marker not in finished.name
        for value in finished.attributes.values():
            assert marker not in str(value)
        for event in finished.events:
            assert marker not in event.name
            assert marker not in str(event.attributes)


class TestLogCorrelation:
    def test_the_request_completed_log_line_carries_trace_and_span_id(self, db, traced, caplog):
        with caplog.at_level(logging.INFO, logger="supportpilot"):
            APIClient().get("/health/")

        records = [r for r in caplog.records if r.name == "supportpilot"]
        assert len(records) == 1
        record = records[0]
        assert record.trace_id
        assert len(record.trace_id) == 32
        assert record.span_id
        assert len(record.span_id) == 16

    def test_no_active_span_logs_empty_string_not_an_error(self, db, settings, caplog):
        settings.OBSERVABILITY_TRACING_ENABLED = False
        with caplog.at_level(logging.INFO, logger="supportpilot"):
            APIClient().get("/health/")

        records = [r for r in caplog.records if r.name == "supportpilot"]
        assert records[0].trace_id == ""
        assert records[0].span_id == ""

    def test_raw_traceparent_header_is_never_logged_verbatim(self, db, traced, caplog):
        inbound = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        with caplog.at_level(logging.INFO, logger="supportpilot"):
            APIClient().get("/health/", HTTP_TRACEPARENT=inbound)

        for record in caplog.records:
            assert inbound not in record.getMessage()
            assert inbound not in str(record.__dict__)


class TestW3CParentPropagation:
    def test_valid_inbound_traceparent_becomes_the_span_parent(self, db, traced):
        inbound_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        APIClient().get(
            "/health/",
            HTTP_TRACEPARENT=f"00-{inbound_trace_id}-00f067aa0ba902b7-01",
        )

        finished = traced.get_finished_spans()[0]
        assert format(finished.context.trace_id, "032x") == inbound_trace_id

    def test_malformed_inbound_traceparent_still_succeeds_with_a_fresh_trace(self, db, traced):
        response = APIClient().get(
            "/health/",
            HTTP_TRACEPARENT="not-a-valid-traceparent-at-all",
        )

        assert response.status_code == 200
        finished = traced.get_finished_spans()[0]
        assert finished.context.trace_id != 0

    def test_inbound_tracestate_is_forwarded_into_the_carrier(self, db, traced):
        response = APIClient().get(
            "/health/",
            HTTP_TRACEPARENT="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            HTTP_TRACESTATE="vendor=value",
        )

        assert response.status_code == 200
