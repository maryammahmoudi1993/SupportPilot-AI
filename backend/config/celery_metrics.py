"""Prefork-safe Celery worker Prometheus exposition (Phase 11 Block 3).

Closes the gap Block 2 explicitly left open (ADR 0009, ``observability/metrics.py``):
``supportpilot_celery_tasks_total``/``_duration_seconds`` were recorded
correctly per-worker-process but never exposed for scraping. A Celery
prefork pool's child processes cannot each bind the same metrics port (they
would race and only one would win), so this mirrors
``config/gunicorn_conf.py``'s own solution to the identical structural
problem, using Celery's own process-lifecycle signals in place of
Gunicorn's server hooks::

    Celery worker main process (parent, pre-fork)
        |  worker_init: fresh PROMETHEUS_MULTIPROC_DIR, one HTTP listener
        v
    prefork children (inherit the env var via fork; never bind a port)
        |  each writes its own per-PID mmap files under that directory
        v
    the one parent-owned HTTP listener
        |  serves render_metrics() — a fresh CollectorRegistry +
        |  MultiProcessCollector reading every child's mmap files fresh
        |  on each scrape (same function Gunicorn's own scrape route uses)
        v
    Prometheus (or any compatible scraper)

Only the parent binds a port, exactly once, before any child exists — never
a per-child listener, never a race for the port. ``worker_process_shutdown``
fires *in the parent* with the dead child's ``pid`` (see
``celery.concurrency.prefork.process_destructor`` — a genuine parent-side
hook, unlike ``worker_process_init``/``worker_process_shutdown``'s naming
might suggest), so ``prometheus_client.multiprocess.mark_process_dead`` is
called from the same place Gunicorn's ``child_exit`` calls it.

Deliberately not Gunicorn's own ``PROMETHEUS_MULTIPROC_DIR``/hooks (section
5): Django/Gunicorn and Celery are typically separate deployable process
groups (often separate containers) and must not be required to share a
filesystem or a directory — ``OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR``
is a distinct setting with its own default path.

Security (section 6): the exposition listener has no authentication of its
own — it is infrastructure telemetry, not a tenant API — so it binds to
``OBSERVABILITY_CELERY_METRICS_HOST`` (default ``127.0.0.1``, loopback-only)
by default. Binding it anywhere else is an explicit, deployment-owned
decision that the surrounding network (a private VPC, a sidecar-only
network namespace, a firewall) is what actually restricts access — this
module never claims that is safe on its own.

Disabled by default (``OBSERVABILITY_CELERY_METRICS_ENABLED=False``):
importing/connecting these signal handlers costs nothing when disabled — no
directory is touched, no port is bound, no thread is started.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from celery.signals import worker_init, worker_process_shutdown
from django.conf import settings

logger = logging.getLogger("supportpilot")

_lock = threading.Lock()
_server: ThreadingHTTPServer | None = None


class _MetricsRequestHandler(BaseHTTPRequestHandler):
    """Serves exactly one route: a Prometheus scrape of this worker
    process group's aggregated metrics. No other path, no query-string
    handling, no tenant auth — an unrecognized path is a plain 404, matching
    ``observability/views.py``'s own "denial is generic" convention (never
    an exception, never a stack trace, in a listener with no request
    validation layer in front of it)."""

    server_version = "SupportPilotCeleryMetrics/1"

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        # The stdlib default logs every request to stderr; this is a
        # low-traffic infra scrape endpoint and normal structured logging
        # already covers the application — silence it rather than adding a
        # second, inconsistent log format.
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler method name
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        from observability.metrics import METRICS_CONTENT_TYPE, render_metrics

        try:
            body = render_metrics()
        except Exception:  # noqa: BLE001 - telemetry must fail open
            logger.warning("celery_metrics_render_failed", extra={"event": "celery_metrics_error"})
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", METRICS_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _setup_multiproc_dir() -> None:
    """Fresh directory, set *before* the prefork pool exists so every child
    inherits ``PROMETHEUS_MULTIPROC_DIR`` via fork and — critically —
    before this worker process itself imports ``observability.metrics``
    (that module decides its value class at import time; see its own
    docstring). Wiped on every worker-master start, mirroring
    ``config/gunicorn_conf.py::on_starting`` exactly: stale mmap files left
    by a previous worker master must never be aggregated into a new one's
    scrape as if they were live processes."""
    multiproc_dir = settings.OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR
    shutil.rmtree(multiproc_dir, ignore_errors=True)
    os.makedirs(multiproc_dir, exist_ok=True)
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir


def _start_exposition_server() -> None:
    """Bind exactly once, in the parent, before any prefork child exists.
    Idempotent (module-level guard) so a redundant ``worker_init`` dispatch
    within one process never attempts a second bind of the same port."""
    global _server
    with _lock:
        if _server is not None:
            return
        host = settings.OBSERVABILITY_CELERY_METRICS_HOST
        port = settings.OBSERVABILITY_CELERY_METRICS_PORT
        try:
            server = ThreadingHTTPServer((host, port), _MetricsRequestHandler)
        except OSError:
            logger.warning(
                "celery_metrics_listener_bind_failed",
                extra={"event": "celery_metrics_error", "host": host, "port": port},
            )
            return
        server.daemon_threads = True
        thread = threading.Thread(
            target=server.serve_forever, name="celery-metrics-exposition", daemon=True
        )
        thread.start()
        _server = server
        logger.info(
            "celery_metrics_listener_started",
            extra={"event": "celery_metrics_started", "host": host, "port": port},
        )


def reset_for_tests() -> None:
    """Test-only: release the module-level server guard so a test can
    exercise :func:`_start_exposition_server`'s bind path from a clean
    state, and actually stop any server a prior test started."""
    global _server
    with _lock:
        if _server is not None:
            try:
                _server.shutdown()
                _server.server_close()
            except Exception:  # noqa: BLE001 - best-effort test cleanup
                pass
        _server = None


@worker_init.connect
def on_worker_init(**kwargs) -> None:  # noqa: ARG001 - required Celery signal signature
    """Runs once, in the worker *master* process, before the prefork pool
    forks any child (mirrors ``config/gunicorn_conf.py::on_starting``).
    Fails open: a broken exposition setup must never prevent the worker
    from starting and processing tasks."""
    if not settings.OBSERVABILITY_CELERY_METRICS_ENABLED:
        return
    try:
        _setup_multiproc_dir()
        _start_exposition_server()
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("celery_metrics_init_failed", extra={"event": "celery_metrics_error"})


@worker_process_shutdown.connect
def on_worker_process_shutdown(pid=None, **kwargs) -> None:  # noqa: ARG001
    """Runs in the *parent* process when a prefork child exits
    (``celery.concurrency.prefork.process_destructor`` sends this signal
    from the pool's own destructor callback, not from the child itself) —
    the same parent-side timing ``config/gunicorn_conf.py::child_exit`` relies
    on. Removes that child's live-gauge mmap files; counter/histogram files
    are retained so cumulative values survive a worker recycle, exactly like
    the Gunicorn hook this mirrors."""
    if not settings.OBSERVABILITY_CELERY_METRICS_ENABLED or pid is None:
        return
    try:
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(pid)
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning(
            "celery_metrics_child_cleanup_failed", extra={"event": "celery_metrics_error"}
        )
