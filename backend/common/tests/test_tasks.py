"""Tests for ``CorrelatedTask`` (Phase 11 Block 2)."""

from __future__ import annotations

import uuid

import pytest
from celery import Celery

from common.correlation import get_correlation_id
from common.tasks import CorrelatedTask
from observability.metrics import METRIC_NAMESPACE
from observability.tests.test_metrics import _sample_value


@pytest.fixture
def celery_app():
    """A throwaway app so tasks defined here don't leak into the real
    Celery app's registry across test runs. Tasks are created via
    ``celery_app.task(...)`` directly, so they carry their own app
    reference — no need to make this the process-global "current" app."""
    app = Celery("test-correlated-task")
    app.conf.task_always_eager = True
    yield app


class TestCorrelatedTaskCorrelationPropagation:
    def test_binds_the_passed_correlation_id_for_the_task_body(self, celery_app):
        observed = {}

        @celery_app.task(base=CorrelatedTask, bind=True)
        def probe(self):
            observed["correlation_id"] = get_correlation_id()

        correlation_id = str(uuid.uuid4())
        probe.apply(kwargs={"correlation_id": correlation_id})

        assert observed["correlation_id"] == correlation_id

    def test_generates_a_fresh_id_when_none_is_passed(self, celery_app):
        observed = {}

        @celery_app.task(base=CorrelatedTask, bind=True)
        def probe(self):
            observed["correlation_id"] = get_correlation_id()

        probe.apply()

        assert observed["correlation_id"] is not None
        uuid.UUID(observed["correlation_id"])  # does not raise

    def test_correlation_id_kwarg_never_reaches_the_task_body(self, celery_app):
        """The task function's own signature must never have to know about
        ``correlation_id`` — it is popped before the wrapped function runs."""

        @celery_app.task(base=CorrelatedTask, bind=True)
        def probe(self, business_arg):
            return business_arg

        result = probe.apply(args=["value"], kwargs={"correlation_id": str(uuid.uuid4())})

        assert result.get() == "value"

    def test_scope_is_unbound_again_after_the_task_completes(self, celery_app):
        @celery_app.task(base=CorrelatedTask, bind=True)
        def probe(self):
            return None

        probe.apply(kwargs={"correlation_id": str(uuid.uuid4())})

        assert get_correlation_id() is None


class TestCorrelatedTaskMetrics:
    def test_records_success_outcome(self, celery_app):
        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tasks.success")
        def succeeds(self):
            return "ok"

        succeeds.apply()

        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_celery_tasks_total",
            labels={"task_name": "test.tasks.success", "outcome": "success"},
        )
        assert value == 1.0

    def test_records_failure_outcome_and_still_propagates_the_exception(self, celery_app):
        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tasks.failure")
        def fails(self):
            raise ValueError("boom")

        result = fails.apply()

        assert result.failed()
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_celery_tasks_total",
            labels={"task_name": "test.tasks.failure", "outcome": "failure"},
        )
        assert value == 1.0

    def test_records_retry_outcome_distinctly_from_failure(self, celery_app):
        """``self.retry()`` under eager/``.apply()`` execution re-raises the
        original exception directly rather than a ``Retry`` (Celery's
        ``Task.retry`` special-cases ``request.called_directly``) — so this
        exercises the ``Retry`` branch directly, the same exception class a
        real worker's ``self.retry()`` raises."""
        from celery.exceptions import Retry

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tasks.retry")
        def retries(self):
            raise Retry("scheduling a retry")

        result = retries.apply()

        assert result.state == "RETRY"
        value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_celery_tasks_total",
            labels={"task_name": "test.tasks.retry", "outcome": "retry"},
        )
        assert value == 1.0
        # A retry is not a failure — the failure label must not also fire.
        failure_value = _sample_value(
            metric_name=f"{METRIC_NAMESPACE}_celery_tasks_total",
            labels={"task_name": "test.tasks.retry", "outcome": "failure"},
        )
        assert failure_value is None

    def test_metrics_recording_failure_does_not_break_task_execution(self, celery_app, monkeypatch):
        """Failure isolation (observability doc section 30): a broken
        metrics call must never affect the task's own result."""
        import observability.metrics as metrics_module

        def _raise(*args, **kwargs):
            raise RuntimeError("metrics backend broken")

        monkeypatch.setattr(metrics_module, "observe_celery_task", _raise)

        @celery_app.task(base=CorrelatedTask, bind=True, name="test.tasks.metrics-fail-open")
        def probe(self):
            return "still works"

        result = probe.apply()

        assert result.get() == "still works"
