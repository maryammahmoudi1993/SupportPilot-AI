"""Celery base task carrying correlation-id propagation and bounded
task-level metrics (Phase 11 Block 2).

Every first-party ``@shared_task`` is declared with ``base=CorrelatedTask``
(never ad hoc per-task instrumentation — section 7's "one call site"
principle, applied to the Celery boundary the same way
``observability.middleware.MetricsMiddleware`` applies it to HTTP). This
keeps every task body itself completely unaware of correlation ids or
metrics: dispatch passes ``correlation_id=...`` as an ordinary task keyword
argument, this base class pops it off before the task body ever sees it,
binds it for the task's duration, and records the outcome — the same
failure-isolation guarantee HTTP metrics already have (recording must never
affect the actual task result) applies here too.

Phase 11 Block 2 remediation (Part B) additionally wraps each task
execution in one ``observability.tracing.task_span`` — a distributed-trace
consumer span parented to whatever W3C context ``_inject_trace_context``
(this module, connected to Celery's ``before_task_publish`` signal) placed
into the message headers at publish time. A duplicate broker redelivery
producing two task executions is expected, by design, to produce two task
spans (section 20) — that is a tracing/observability artifact only, and
must never be read as evidence of two ``DeliveryAttempt``s or two external
sends; Phase 10's claim/idempotency behavior alone is what prevents that,
completely independent of how many spans a delivery's retries produced.
"""

from __future__ import annotations

import logging
import time

from celery import Task
from celery.exceptions import Retry
from celery.signals import before_task_publish

from .correlation import correlation_scope, new_correlation_id

logger = logging.getLogger("supportpilot")


@before_task_publish.connect
def _inject_trace_context(headers=None, **kwargs) -> None:  # noqa: ARG001
    """Inject the active W3C trace context into outbound Celery message
    headers (Phase 11 Block 2 remediation, section 15) — never into
    business task kwargs, keeping Part A's ``correlation_id`` kwarg design
    untouched (section 14).

    Connected once at import time (this module is already imported by
    every first-party task via ``base=CorrelatedTask`` — Part A's existing
    "one call site" boundary), so this fires for every real
    ``apply_async``/``delay`` publish without any per-call-site change.
    Deliberately guarded regardless of Celery's own signal-dispatch error
    handling: injection failure must never prevent task publication
    (section 15/25)."""
    if headers is None:
        return
    try:
        from observability.tracing import inject_context

        inject_context(headers)
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("tracing_publish_injection_failed", extra={"event": "tracing_error"})


class CorrelatedTask(Task):
    """Base class for every first-party Celery task.

    Dispatch call sites pass ``correlation_id=get_correlation_id()`` (falling
    back to ``None`` when there is no active HTTP request/task scope, e.g. a
    Beat-triggered sweep) as a normal task keyword argument — never via task
    args a worker would need to distinguish from real parameters, and never
    via message headers, so it works identically under eager execution,
    ``.apply()``, and every existing test that dispatches these tasks
    directly. A missing/``None`` id gets a fresh one generated here so every
    task execution is always attributable to *some* correlation id.
    """

    def __call__(self, *args, **kwargs):
        from observability.tracing import finalize_task_span, task_span

        correlation_id = kwargs.pop("correlation_id", None) or new_correlation_id()
        start = time.monotonic()
        # Custom message headers set by ``_inject_trace_context`` above
        # (real dispatch) or passed directly to ``.apply(headers=...)``
        # (eager/test dispatch) — both surface identically as
        # ``self.request.headers`` (section 16). Absent under plain
        # ``.apply()``/direct calls with no ``headers`` kwarg at all, which
        # is fine: extraction of an empty carrier safely yields no parent.
        trace_headers = getattr(self.request, "headers", None) or {}
        with correlation_scope(correlation_id):
            with task_span(self.name, headers=trace_headers) as span:
                try:
                    result = super().__call__(*args, **kwargs)
                except Retry:
                    self._observe(start, outcome="retry")
                    finalize_task_span(span, outcome="retry")
                    raise
                except Exception:
                    self._observe(start, outcome="failure")
                    finalize_task_span(span, outcome="failure")
                    raise
                else:
                    self._observe(start, outcome="success")
                    finalize_task_span(span, outcome="success")
                    return result

    def _observe(self, start: float, *, outcome: str) -> None:
        from observability.metrics import observe_celery_task

        try:
            observe_celery_task(
                task_name=self.name,
                outcome=outcome,
                duration_seconds=time.monotonic() - start,
            )
        except Exception:  # noqa: BLE001 - telemetry must fail open (section 30)
            logger.warning(
                "celery_metrics_recording_failed",
                extra={"event": "metrics_error", "task_name": self.name},
            )
