"""Tests for the tracing boundary itself (Phase 11 Block 2 remediation,
Part B)."""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.trace import SpanKind
from opentelemetry.trace.status import StatusCode

from observability import tracing


class TestDisabledMode:
    """Section 6/34: tracing disabled must add zero startup dependency and
    every helper must degrade to a harmless no-op."""

    def test_server_span_yields_none_when_disabled(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = False
        with tracing.server_span("HTTP request") as span:
            assert span is None

    def test_task_span_yields_none_when_disabled(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = False
        with tracing.task_span("some.task") as span:
            assert span is None

    def test_get_trace_id_and_span_id_are_none_when_disabled(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = False
        assert tracing.get_trace_id() is None
        assert tracing.get_span_id() is None

    def test_extract_context_returns_none_when_disabled(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = False
        assert tracing.extract_context({"traceparent": "anything"}) is None

    def test_inject_context_is_a_no_op_when_disabled(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = False
        carrier: dict[str, str] = {}
        tracing.inject_context(carrier)
        assert carrier == {}

    def test_finalize_and_mark_error_are_safe_with_no_span(self):
        # No span (None) must never raise regardless of the enabled flag.
        tracing.finalize_server_span(None, method="GET", route="x", status_code=200)
        tracing.finalize_task_span(None, outcome="success")
        tracing.mark_span_error(None)


class TestServerSpanCreation:
    def test_creates_a_real_span_with_valid_trace_and_span_ids(self, traced):
        with tracing.server_span("HTTP request") as span:
            assert span is not None
            assert tracing.get_trace_id() is not None
            assert tracing.get_span_id() is not None
        finished = traced.get_finished_spans()
        assert len(finished) == 1

    def test_trace_id_is_32_lowercase_hex_characters(self, traced):
        with tracing.server_span("HTTP request"):
            trace_id = tracing.get_trace_id()
        assert len(trace_id) == 32
        assert trace_id == trace_id.lower()
        int(trace_id, 16)  # does not raise

    def test_span_id_is_16_lowercase_hex_characters(self, traced):
        with tracing.server_span("HTTP request"):
            span_id = tracing.get_span_id()
        assert len(span_id) == 16
        assert span_id == span_id.lower()
        int(span_id, 16)  # does not raise

    def test_finalize_server_span_sets_bounded_http_attributes(self, traced):
        with tracing.server_span("HTTP request") as span:
            tracing.finalize_server_span(span, method="GET", route="health:health", status_code=200)
        finished = traced.get_finished_spans()[0]
        assert finished.attributes["http.request.method"] == "GET"
        assert finished.attributes["http.route"] == "health:health"
        assert finished.attributes["http.response.status_code"] == 200
        assert finished.name == "HTTP GET health:health"
        assert finished.status.status_code == StatusCode.OK

    def test_finalize_server_span_marks_5xx_as_error_status_only(self, traced):
        with tracing.server_span("HTTP request") as span:
            tracing.finalize_server_span(span, method="GET", route="x", status_code=500)
        finished = traced.get_finished_spans()[0]
        assert finished.status.status_code == StatusCode.ERROR
        # Safe status metadata only (section 23) — no description/message text.
        assert not finished.status.description


class TestTaskSpanCreation:
    def test_creates_a_consumer_span_with_task_name_attribute(self, traced):
        with tracing.task_span("notifications.tasks.dispatch") as span:
            assert span is not None
        finished = traced.get_finished_spans()[0]
        assert finished.kind == SpanKind.CONSUMER
        assert finished.attributes["celery.task_name"] == "notifications.tasks.dispatch"
        assert finished.name == "celery.task notifications.tasks.dispatch"

    def test_finalize_task_span_records_bounded_outcome_only(self, traced):
        with tracing.task_span("t") as span:
            tracing.finalize_task_span(span, outcome="retry")
        finished = traced.get_finished_spans()[0]
        assert finished.attributes["supportpilot.task_outcome"] == "retry"

    def test_unbounded_outcome_value_collapses_to_failure(self, traced):
        with tracing.task_span("t") as span:
            tracing.finalize_task_span(span, outcome="something-unbounded")
        finished = traced.get_finished_spans()[0]
        assert finished.attributes["supportpilot.task_outcome"] == "failure"

    def test_task_span_never_carries_args_kwargs_or_payload_attributes(self, traced):
        with tracing.task_span("t") as span:
            tracing.finalize_task_span(span, outcome="success")
        finished = traced.get_finished_spans()[0]
        assert set(finished.attributes.keys()) <= {"celery.task_name", "supportpilot.task_outcome"}


class TestDomainSpanCreation:
    def test_creates_an_internal_span_with_extra_attributes(self, traced):
        with tracing.domain_span(
            "agent.run", attributes={"supportpilot.agent_run_id": "x"}
        ) as span:
            assert span is not None
        finished = traced.get_finished_spans()[0]
        assert finished.kind == SpanKind.INTERNAL
        assert finished.name == "agent.run"
        assert finished.attributes["supportpilot.agent_run_id"] == "x"

    def test_finalize_domain_span_records_outcome_and_extra_attributes(self, traced):
        with tracing.domain_span("tool.execute") as span:
            tracing.finalize_domain_span(
                span, outcome="succeeded", extra_attributes={"tool.name": "payment.refund"}
            )
        finished = traced.get_finished_spans()[0]
        assert finished.attributes["supportpilot.outcome"] == "succeeded"
        assert finished.attributes["tool.name"] == "payment.refund"
        assert finished.status.status_code == StatusCode.OK

    def test_finalize_domain_span_is_error_sets_error_status_only(self, traced):
        with tracing.domain_span("tool.execute") as span:
            tracing.finalize_domain_span(span, outcome="failed", is_error=True)
        finished = traced.get_finished_spans()[0]
        assert finished.status.status_code == StatusCode.ERROR
        assert not finished.status.description

    def test_finalize_domain_span_with_no_span_is_a_safe_no_op(self):
        tracing.finalize_domain_span(None, outcome="success")  # must not raise


class TestBusinessExceptionPropagation:
    """A tracing span must never swallow the caller's own exception."""

    def test_server_span_lets_the_caller_exception_propagate(self, traced):
        class Boom(Exception):
            pass

        try:
            with tracing.server_span("HTTP request"):
                raise Boom("business failure")
        except Boom:
            pass
        else:
            raise AssertionError("business exception was swallowed by the tracing span")

    def test_task_span_lets_the_caller_exception_propagate(self, traced):
        class Boom(Exception):
            pass

        try:
            with tracing.task_span("t"):
                raise Boom("business failure")
        except Boom:
            pass
        else:
            raise AssertionError("business exception was swallowed by the tracing span")

    def test_no_raw_exception_is_recorded_onto_the_span(self, traced):
        """Section 21 — hard security gate: even when the wrapped body
        raises, the span must never carry ``record_exception`` event data
        derived from that exception's text."""

        class Boom(Exception):
            pass

        try:
            with tracing.server_span("HTTP request"):
                raise Boom("SUPER_SECRET_TRACE_MARKER_284731")
        except Boom:
            pass
        finished = traced.get_finished_spans()[0]
        for event in finished.events:
            assert "SUPER_SECRET_TRACE_MARKER_284731" not in str(event.attributes)
            assert "SUPER_SECRET_TRACE_MARKER_284731" not in event.name


class TestFailureIsolation:
    def test_broken_span_start_still_yields_none_and_does_not_raise(self, settings, monkeypatch):
        settings.OBSERVABILITY_TRACING_ENABLED = True

        class _BrokenTracer:
            def start_as_current_span(self, *args, **kwargs):
                raise RuntimeError("tracer backend exploded")

        monkeypatch.setattr(tracing, "get_tracer", lambda: _BrokenTracer())

        with tracing.server_span("HTTP request") as span:
            assert span is None

    def test_extract_context_failure_yields_none_not_an_exception(self, settings, monkeypatch):
        settings.OBSERVABILITY_TRACING_ENABLED = True

        def _boom(carrier):
            raise RuntimeError("propagator exploded")

        monkeypatch.setattr(tracing, "_otel_extract", _boom)

        assert tracing.extract_context({"traceparent": "x"}) is None

    def test_inject_context_failure_does_not_raise(self, settings, monkeypatch):
        settings.OBSERVABILITY_TRACING_ENABLED = True

        def _boom(carrier):
            raise RuntimeError("propagator exploded")

        monkeypatch.setattr(tracing, "_otel_inject", _boom)

        tracing.inject_context({})  # must not raise

    def test_span_end_failure_does_not_raise(self, traced, monkeypatch):
        real_start = tracing.get_tracer().start_as_current_span

        class _BrokenExitSpanCm:
            def __init__(self, inner):
                self._inner = inner

            def __enter__(self):
                return self._inner.__enter__()

            def __exit__(self, *exc_info):
                raise RuntimeError("span end exploded")

        def _wrapped(*args, **kwargs):
            return _BrokenExitSpanCm(real_start(*args, **kwargs))

        monkeypatch.setattr(tracing.get_tracer(), "start_as_current_span", _wrapped)

        with tracing.server_span("HTTP request") as span:
            assert span is not None  # must not raise on span end either

    def test_mark_span_error_failure_does_not_raise(self, traced, monkeypatch):
        class _BrokenSpan:
            def set_status(self, *args, **kwargs):
                raise RuntimeError("status update exploded")

        tracing.mark_span_error(_BrokenSpan())  # must not raise

    def test_finalize_server_span_failure_does_not_raise(self, traced):
        class _BrokenSpan:
            def update_name(self, *args, **kwargs):
                raise RuntimeError("update_name exploded")

        tracing.finalize_server_span(
            _BrokenSpan(), method="GET", route="x", status_code=200
        )  # must not raise

    def test_finalize_task_span_failure_does_not_raise(self, traced):
        class _BrokenSpan:
            def set_attribute(self, *args, **kwargs):
                raise RuntimeError("set_attribute exploded")

        tracing.finalize_task_span(_BrokenSpan(), outcome="success")  # must not raise

    def test_finalize_domain_span_failure_does_not_raise(self, traced):
        class _BrokenSpan:
            def set_attribute(self, *args, **kwargs):
                raise RuntimeError("set_attribute exploded")

        tracing.finalize_domain_span(_BrokenSpan(), outcome="success")  # must not raise

    def test_get_trace_id_failure_returns_none(self, settings, monkeypatch):
        settings.OBSERVABILITY_TRACING_ENABLED = True

        class _BrokenSpan:
            def get_span_context(self):
                raise RuntimeError("span context exploded")

        monkeypatch.setattr(trace, "get_current_span", lambda: _BrokenSpan())

        assert tracing.get_trace_id() is None

    def test_get_span_id_failure_returns_none(self, settings, monkeypatch):
        settings.OBSERVABILITY_TRACING_ENABLED = True

        class _BrokenSpan:
            def get_span_context(self):
                raise RuntimeError("span context exploded")

        monkeypatch.setattr(trace, "get_current_span", lambda: _BrokenSpan())

        assert tracing.get_span_id() is None

    def test_log_filter_failure_still_logs_empty_ids(self, settings, monkeypatch):
        settings.OBSERVABILITY_TRACING_ENABLED = True

        def _boom():
            raise RuntimeError("id lookup exploded")

        monkeypatch.setattr(tracing, "get_trace_id", _boom)
        record = logging.LogRecord(
            name="supportpilot",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )

        assert tracing.TraceContextLogFilter().filter(record) is True
        assert record.trace_id == ""
        assert record.span_id == ""


class TestMalformedW3CContext:
    """Section 12-13: malformed inbound traceparent must never fail the
    request and must never leak the raw malformed value."""

    def test_invalid_version_is_ignored_not_raised(self, traced):
        context = tracing.extract_context(
            {"traceparent": "99-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        )
        with tracing.server_span("HTTP request", parent_context=context) as span:
            assert span is not None  # a fresh local span, not a failure

    def test_invalid_hex_is_ignored_not_raised(self, traced):
        context = tracing.extract_context(
            {"traceparent": "00-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-00f067aa0ba902b7-01"}
        )
        with tracing.server_span("HTTP request", parent_context=context):
            pass

    def test_all_zero_trace_id_is_ignored_not_raised(self, traced):
        context = tracing.extract_context(
            {"traceparent": "00-00000000000000000000000000000000-00f067aa0ba902b7-01"}
        )
        with tracing.server_span("HTTP request", parent_context=context):
            pass

    def test_all_zero_parent_span_id_is_ignored_not_raised(self, traced):
        context = tracing.extract_context(
            {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01"}
        )
        with tracing.server_span("HTTP request", parent_context=context):
            pass

    def test_bad_separators_are_ignored_not_raised(self, traced):
        context = tracing.extract_context(
            {"traceparent": "00_4bf92f3577b34da6a3ce929d0e0e4736_00f067aa0ba902b7_01"}
        )
        with tracing.server_span("HTTP request", parent_context=context):
            pass

    def test_oversized_traceparent_is_ignored_not_raised(self, traced):
        context = tracing.extract_context({"traceparent": "00-" + "a" * 5000})
        with tracing.server_span("HTTP request", parent_context=context):
            pass

    def test_malformed_tracestate_is_ignored_not_raised(self, traced):
        context = tracing.extract_context(
            {
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "tracestate": "\x00\x01 not-a-valid-tracestate ==,,,",
            }
        )
        with tracing.server_span("HTTP request", parent_context=context):
            pass

    def test_valid_traceparent_becomes_the_parent_trace_id(self, traced):
        inbound_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        context = tracing.extract_context(
            {"traceparent": f"00-{inbound_trace_id}-00f067aa0ba902b7-01"}
        )
        with tracing.server_span("HTTP request", parent_context=context):
            assert tracing.get_trace_id() == inbound_trace_id


class TestProviderIdempotency:
    def test_get_tracer_provider_is_the_same_object_across_calls(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = True
        tracing.use_provider_for_tests(None)
        try:
            first = tracing.get_tracer_provider()
            second = tracing.get_tracer_provider()
            assert first is second
        finally:
            tracing.use_provider_for_tests(None)

    def test_repeated_init_across_many_calls_does_not_raise(self, settings):
        settings.OBSERVABILITY_TRACING_ENABLED = True
        tracing.use_provider_for_tests(None)
        try:
            for _ in range(5):
                tracing.get_tracer_provider()
        finally:
            tracing.use_provider_for_tests(None)
