"""Central, bounded-cardinality metrics registry (Phase 11 Block 1).

Every metric defined anywhere in this application is declared exactly once,
in this module — never ad hoc inside a view, service, or task — so that
names, label sets, and cardinality can be reviewed in one place (section 7).

Cardinality is a release-critical property, not a style preference (section
8): a metric label populated from an unbounded value (a workspace/customer/
delivery/request id, a raw URL, an exception message, a provider response
body) turns one time series into an unbounded number of them, which is a
real production outage vector for any metrics backend. Every label used
anywhere in this module is drawn from a small, server-owned, bounded set —
see each metric's docstring for its exact allowed values.

Multiprocess correctness (section 29): production runs multiple Gunicorn
worker processes and separate Celery worker processes. ``prometheus_client``
decides, at metric *construction* time (i.e. at module import time, once per
process), whether to use its multiprocess-safe value class — purely by
checking whether ``PROMETHEUS_MULTIPROC_DIR`` is present in the environment.
This means that env var must already be set, pointing at an existing,
per-deployment-fresh directory, before this module is first imported —
before Gunicorn forks its workers. Each process then writes its samples to
per-process mmap files under that directory rather than sharing one
in-memory registry. Rendering a scrape (``render_metrics`` below) is what
differs from single-process mode: it builds a *fresh* ``CollectorRegistry``
wired to a ``MultiProcessCollector`` that reads and aggregates every
process's mmap files at scrape time, instead of reading process-local memory
directly. See ``docs/architecture/observability.md`` for the full
explanation and ``config/gunicorn_conf.py`` for the required
worker-lifecycle cleanup hook.
"""

from __future__ import annotations

import os

from prometheus_client import CONTENT_TYPE_LATEST as METRICS_CONTENT_TYPE
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

__all__ = [
    "METRIC_NAMESPACE",
    "METRICS_CONTENT_TYPE",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "CELERY_TASKS_TOTAL",
    "CELERY_TASK_DURATION_SECONDS",
    "observe_http_request",
    "observe_celery_task",
    "render_metrics",
]

METRIC_NAMESPACE = "supportpilot"

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

#: Labels: ``method`` (one of ``GET``/``POST``/``PUT``/``PATCH``/``DELETE``/
#: ``HEAD``/``OPTIONS``/``OTHER``), ``route`` (the
#: resolved Django URL name, e.g. ``"webhook-endpoint-detail"`` — bounded by
#: the URLconf, never the raw request path/querystring; unresolved paths are
#: collapsed to the single value ``"unmatched"`` rather than one series per
#: probed path — see ``observability/middleware.py``), ``status_class``
#: (``"2xx"``/``"3xx"``/``"4xx"``/``"5xx"``/``"other"`` — 5 values).
HTTP_REQUESTS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_http_requests_total",
    "Total HTTP requests handled, by method/route/status class.",
    ["method", "route", "status_class"],
)

#: Same bounded label set as ``HTTP_REQUESTS_TOTAL`` minus ``status_class``
#: (duration buckets already convey outcome-independent cost; keeping the
#: label set here smaller bounds bucket-count multiplication).
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_http_request_duration_seconds",
    "HTTP request duration in seconds, by method/route.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)


_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_HTTP_STATUS_CLASSES = frozenset({2, 3, 4, 5})


def _http_method(method: str) -> str:
    """Collapse attacker-controlled/custom HTTP verbs to one stable label."""
    normalized_method = method.upper()
    return normalized_method if normalized_method in _HTTP_METHODS else "OTHER"


def _status_class(status_code: int) -> str:
    """Return a bounded class even if application code emits an invalid status."""
    status_class = status_code // 100
    return f"{status_class}xx" if status_class in _HTTP_STATUS_CLASSES else "other"


def observe_http_request(
    *, method: str, route: str, status_code: int, duration_seconds: float
) -> None:
    """The single call site every HTTP metrics recorder must go through
    (section 7) — keeps the two HTTP metrics' label values consistent with
    each other by construction."""
    method_label = _http_method(method)
    status_class = _status_class(status_code)
    HTTP_REQUESTS_TOTAL.labels(method=method_label, route=route, status_class=status_class).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method_label, route=route).observe(duration_seconds)


# ---------------------------------------------------------------------------
# Celery tasks (Phase 11 Block 2)
# ---------------------------------------------------------------------------
#
# Recorded from ``common.tasks.CorrelatedTask`` — every first-party
# ``@shared_task`` is defined with ``base=CorrelatedTask``, so this is the
# single call site for both metrics, exactly like ``observe_http_request``
# above.
#
# Deployment note: Celery workers deliberately run in ``prometheus_client``'s
# default single-process mode (see ``docs/architecture/observability.md``),
# so these metrics accumulate correctly in-process but are not yet exposed
# for scraping from a worker — that requires a worker-process-safe HTTP
# exposition strategy (multiple prefork children cannot share one port) and
# is left to a later block, matching the operational gap ADR 0009 already
# flagged. Until then these metrics are directly assertable in tests and
# ready for that later block to expose, not yet scrapeable in production.

#: Labels: ``task_name`` (the Celery task's registered name — bounded
#: because it is drawn from this codebase's own ``@shared_task``
#: definitions, never from task input), ``outcome`` (``"success"`` /
#: ``"failure"`` / ``"retry"`` — 3 values).
CELERY_TASKS_TOTAL = Counter(
    f"{METRIC_NAMESPACE}_celery_tasks_total",
    "Total Celery tasks executed, by task name and outcome.",
    ["task_name", "outcome"],
)

#: Same bounded label set as ``HTTP_REQUEST_DURATION_SECONDS``'s ``route``:
#: ``task_name`` only — outcome-independent cost, keeping bucket-count
#: multiplication bounded.
CELERY_TASK_DURATION_SECONDS = Histogram(
    f"{METRIC_NAMESPACE}_celery_task_duration_seconds",
    "Celery task execution duration in seconds, by task name.",
    ["task_name"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300),
)

_CELERY_OUTCOMES = frozenset({"success", "failure", "retry"})


def observe_celery_task(*, task_name: str, outcome: str, duration_seconds: float) -> None:
    """The single call site every Celery metrics recorder must go through
    (mirrors ``observe_http_request`` above)."""
    outcome_label = outcome if outcome in _CELERY_OUTCOMES else "failure"
    CELERY_TASKS_TOTAL.labels(task_name=task_name, outcome=outcome_label).inc()
    CELERY_TASK_DURATION_SECONDS.labels(task_name=task_name).observe(duration_seconds)


# ---------------------------------------------------------------------------
# Rendering (multiprocess-aware — section 29)
# ---------------------------------------------------------------------------


def render_metrics() -> bytes:
    """Render the current Prometheus exposition payload.

    Branches on ``PROMETHEUS_MULTIPROC_DIR`` at *render* time so a scrape
    always aggregates whatever is currently on disk. This does not change
    which value class an already-constructed metric object uses (that was
    fixed at import time, per the module docstring) — it only decides how
    this function collects the numbers for the response."""
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiproc_dir:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=multiproc_dir)
        return generate_latest(registry)
    return generate_latest()
