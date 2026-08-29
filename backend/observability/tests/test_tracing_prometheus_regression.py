"""Section 30: request_id/trace_id/span_id must never become Prometheus
labels, and no metric series is created per trace (Phase 11 Block 2
remediation)."""

from __future__ import annotations

import uuid

from rest_framework.test import APIClient

from observability.metrics import render_metrics


class TestNoPerTraceCardinality:
    def test_many_distinct_traces_and_request_ids_stay_bounded_label_sets(self, db, traced):
        for _ in range(20):
            APIClient().get("/health/", HTTP_X_REQUEST_ID=str(uuid.uuid4()))

        body = render_metrics().decode("utf-8")

        assert "request_id" not in body
        assert "trace_id" not in body
        assert "span_id" not in body

        for span in traced.get_finished_spans():
            trace_id_hex = format(span.context.trace_id, "032x")
            assert trace_id_hex not in body
