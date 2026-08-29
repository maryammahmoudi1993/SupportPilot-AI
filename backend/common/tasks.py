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
"""

from __future__ import annotations

import logging
import time

from celery import Task
from celery.exceptions import Retry

from .correlation import correlation_scope, new_correlation_id

logger = logging.getLogger("supportpilot")


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
        correlation_id = kwargs.pop("correlation_id", None) or new_correlation_id()
        start = time.monotonic()
        with correlation_scope(correlation_id):
            try:
                result = super().__call__(*args, **kwargs)
            except Retry:
                self._observe(start, outcome="retry")
                raise
            except Exception:
                self._observe(start, outcome="failure")
                raise
            else:
                self._observe(start, outcome="success")
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
