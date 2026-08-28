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
    "observe_http_request",
    "render_metrics",
]

METRIC_NAMESPACE = "supportpilot"

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

#: Labels: ``method`` (HTTP verb — bounded, ~9 values), ``route`` (the
#: resolved Django URL name, e.g. ``"webhook-endpoint-detail"`` — bounded by
#: the URLconf, never the raw request path/querystring; unresolved paths are
#: collapsed to the single value ``"unmatched"`` rather than one series per
#: probed path — see ``observability/middleware.py``), ``status_class``
#: (``"2xx"``/``"3xx"``/``"4xx"``/``"5xx"`` — 4 values).
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


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def observe_http_request(
    *, method: str, route: str, status_code: int, duration_seconds: float
) -> None:
    """The single call site every HTTP metrics recorder must go through
    (section 7) — keeps the two HTTP metrics' label values consistent with
    each other by construction."""
    status_class = _status_class(status_code)
    HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status_class=status_class).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(duration_seconds)


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
