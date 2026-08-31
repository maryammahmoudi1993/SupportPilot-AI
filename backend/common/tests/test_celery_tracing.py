"""Tests for Celery distributed-trace propagation (Phase 11 Block 2
remediation, sections 14-20, 25-26, 35-36)."""

from __future__ import annotations

import uuid

import pytest
from celery import Celery

from common.correlation import get_correlation_id
from common.tasks import CorrelatedTask, _inject_trace_context
from observability import tracing


@pytest.fixture
def celery_app():
    app = Celery("test-celery-tracing")
    app.conf.task_always_eager = True
    yield app


class TestBusinessKwargsUntouched:
    """Section 14: trace context must never be added to business task
    kwargs — only to message headers."""

    def test_correlation_id_kwarg_still_works_exactly_as_before(self, celery_app, traced):
        observed = {}

        @celery_app.task(base=CorrelatedTask, bind=True)
        def probe(self, business_arg):
            observed["business_arg"] = business_arg
            observed["correlation_id"] = get_correlation_id()

        correlation_id = str(uuid.uuid4())
        probe.apply(args=["value"], kwargs={"correlation_id": correlation_id})

        assert observed["business_arg"] == "value"
        assert observed["correlation_id"] == correlation_id

    def test_task_body_signature_never_needs_a_trace_context_parameter(self, celery_app, traced):
        @celery_app.task(base=CorrelatedTask, bind=True)
        def probe(self, business_arg):
            return business_arg

        result = probe.apply(args=["ok"], headers={"traceparent": "not-inspected-by-body"})
        assert result.get() == "ok"


class TestPublishInjection:
    def test_before_task_publish_writes_a_valid_traceparent_into_headers(self, traced):
        with tracing.server_span("HTTP request"):
            headers: dict[str, str] = {}
            _inject_trace_context(headers=headers)

        assert "traceparent" in headers
        assert headers["traceparent"].count("-") == 3

    def test_no_active_span_leaves_headers_without_a_traceparent(self, traced):
        headers: dict[str, str] = {}
        _inject_trace_context(headers=headers)

        assert "traceparent" not in headers

    def test_none_headers_is_a_safe_no_op(self, traced):
        _inject_trace_context(headers=None)  # must not raise

    def test_injection_failure_never_raises(self, traced, monkeypatch):
        """Section 15/25: injection failure must never prevent task
        publication — the signal handler itself must not raise."""

        def _boom(carrier):
            raise RuntimeError("propagator exploded")

        monkeypatch.setattr("observability.tracing.inject_context", _boom)

        _inject_trace_context(headers={})  # must not raise


class TestWorkerExtractionAndTaskSpan:
    def test_worker_extracts_trace_context_from_message_headers(self, celery_app, traced):
        with tracing.server_span("HTTP request"):
            publish_headers: dict[str, str] = {}
            _inject_trace_context(headers=publish_headers)
            parent_trace_id = tracing.get_trace_id()

        observed = {}

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.worker-extract")
        def probe(self):
            observed["trace_id"] = tracing.get_trace_id()

        probe.apply(headers=publish_headers)

        assert observed["trace_id"] == parent_trace_id

    def test_extraction_failure_still_runs_the_business_task(self, celery_app, traced, monkeypatch):
        """Section 26: malformed/broken telemetry metadata must never
        prevent business task execution."""
        monkeypatch.setattr(
            "observability.tracing._otel_extract",
            lambda carrier: (_ for _ in ()).throw(RuntimeError("broken propagator")),
        )

        observed = {}

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.extract-fail")
        def probe(self):
            observed["ran"] = True

        probe.apply(
            headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        )

        assert observed["ran"] is True

    def test_task_span_records_bounded_task_name_and_outcome(self, celery_app, traced):
        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.outcome")
        def succeeds(self):
            return "ok"

        succeeds.apply()

        finished = [
            s for s in traced.get_finished_spans() if s.name == "celery.task test.tracing.outcome"
        ]
        assert len(finished) == 1
        assert finished[0].attributes["celery.task_name"] == "test.tracing.outcome"
        assert finished[0].attributes["supportpilot.task_outcome"] == "success"

    def test_failure_outcome_recorded_and_exception_still_propagates(self, celery_app, traced):
        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.fails")
        def fails(self):
            raise ValueError("boom")

        result = fails.apply()

        assert result.failed()
        finished = [
            s for s in traced.get_finished_spans() if s.name == "celery.task test.tracing.fails"
        ]
        assert finished[0].attributes["supportpilot.task_outcome"] == "failure"

    def test_no_raw_exception_recorded_onto_the_task_span(self, celery_app, traced):
        """Section 21/22 hard gate, exercised through the real Celery
        boundary this time (not just observability.tracing directly)."""

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.secret-exc")
        def fails(self):
            raise RuntimeError("SUPER_SECRET_TRACE_MARKER_284731")

        fails.apply()

        finished = [
            s
            for s in traced.get_finished_spans()
            if s.name == "celery.task test.tracing.secret-exc"
        ]
        span = finished[0]
        for event in span.events:
            assert "SUPER_SECRET_TRACE_MARKER_284731" not in event.name
            assert "SUPER_SECRET_TRACE_MARKER_284731" not in str(event.attributes)
        for value in span.attributes.values():
            assert "SUPER_SECRET_TRACE_MARKER_284731" not in str(value)


class TestContextIsolation:
    def test_sequential_tasks_do_not_inherit_each_others_trace(self, celery_app, traced):
        observed = {}

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.task-a")
        def task_a(self):
            observed["trace_a"] = tracing.get_trace_id()

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.task-b")
        def task_b(self):
            observed["trace_b"] = tracing.get_trace_id()

        task_a.apply()
        task_b.apply()

        assert observed["trace_a"] != observed["trace_b"]

    def test_correlation_id_scope_still_isolated_alongside_trace_context(self, celery_app, traced):
        observed = {}

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.corr-a")
        def task_a(self):
            observed["a"] = get_correlation_id()

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.corr-b")
        def task_b(self):
            observed["b"] = get_correlation_id()

        task_a.apply(kwargs={"correlation_id": "id-a"})
        task_b.apply(kwargs={"correlation_id": "id-b"})

        assert observed["a"] == "id-a"
        assert observed["b"] == "id-b"
        assert get_correlation_id() is None


class TestTraceContextIsNotBusinessAuthority:
    def test_malformed_trace_context_does_not_alter_task_result(self, celery_app, traced):
        """Section 36: replaying a task with old/malformed trace context
        must still execute with current business inputs — trace metadata
        must never influence business outcome."""

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.business-authority")
        def compute(self, value):
            return value * 2

        malformed_headers = {"traceparent": "not-a-real-traceparent"}
        result = compute.apply(args=[21], headers=malformed_headers)

        assert result.get() == 42


class TestEndToEndHttpToCeleryTrace:
    def test_valid_parent_flows_from_http_span_through_publish_to_worker_task_span(
        self, celery_app, traced
    ):
        """Section 35: assert the actual trace/parent relationship via
        captured span data, not merely that a ``traceparent`` string
        exists."""
        observed = {}

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tracing.e2e")
        def worker_task(self):
            observed["task_trace_id"] = tracing.get_trace_id()
            observed["task_span_id"] = tracing.get_span_id()

        with tracing.server_span("HTTP request"):
            http_trace_id = tracing.get_trace_id()
            http_span_id = tracing.get_span_id()

            publish_headers: dict[str, str] = {}
            _inject_trace_context(headers=publish_headers)

            worker_task.apply(headers=publish_headers)

        assert observed["task_trace_id"] == http_trace_id
        # The task span is a *child* of the HTTP span, not the same span.
        assert observed["task_span_id"] != http_span_id

        finished_by_name = {s.name: s for s in traced.get_finished_spans()}
        task_span_data = finished_by_name["celery.task test.tracing.e2e"]
        http_span_data = finished_by_name["HTTP request"]
        assert format(task_span_data.parent.span_id, "016x") == format(
            http_span_data.context.span_id, "016x"
        )
        assert task_span_data.context.trace_id == http_span_data.context.trace_id
