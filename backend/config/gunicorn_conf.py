"""Gunicorn configuration (Phase 11 Block 1).

Exists solely to make ``prometheus_client``'s multiprocess metrics mode
correct under Gunicorn's multi-worker model (section 29, release-critical):

* ``on_starting`` runs once, in the master process, *before* any worker is
  forked. It sets ``PROMETHEUS_MULTIPROC_DIR`` to a fresh, empty directory —
  fresh on every process start, because stale mmap files left over from a
  previous run (a previous container, a previous deploy) would otherwise be
  aggregated into the current scrape as if they were live workers. Because
  environment variables set here are inherited across ``fork()``, every
  worker process that is forked afterwards sees the same variable already
  present *before* it imports ``observability.metrics`` — which is exactly
  the timing ``prometheus_client`` requires (see that module's docstring).
* ``child_exit`` runs in the master whenever a worker process exits and
  calls ``prometheus_client.multiprocess.mark_process_dead``. The client
  removes that worker's live-gauge files; counter and histogram files are
  deliberately retained so their cumulative values survive a worker recycle,
  then removed by ``on_starting`` at the next master start. Block 1 currently
  defines counters and histograms only, but the hook keeps future live gauges
  correct as well.

Only ``gunicorn`` (the production web process) uses this file — Celery
workers and ``manage.py`` commands are deliberately left in
``prometheus_client``'s default single-process mode (no
``PROMETHEUS_MULTIPROC_DIR`` set for them), matching section 64's
requirement that ordinary local/dev/test/management-command runs stay
simple and need no multiprocess directory to exist at all.

Distributed tracing (Phase 11 Block 2 remediation, ``observability/tracing.py``)
deliberately needs no equivalent pre-fork hook here: its ``TracerProvider``
is built lazily, per-process, on first use (not at import time, not in the
Gunicorn master), and this block ships no span processor/exporter — so
there is no background export thread whose fork-safety would need managing
the way ``PROMETHEUS_MULTIPROC_DIR`` needs to be set before fork. Each
worker process that ends up calling into tracing builds its own provider
independently, after it is already running as a distinct process.

Worker count and timeouts (Phase 17): configurable via environment, never
derived from the build/dev-host CPU count — a container's host may have far
more cores than the deployment should actually spend on one web replica.
Defaults are conservative, matching the ``--workers 3`` this file used to
hardcode via the Dockerfile CMD before these became env-driven.
"""

from __future__ import annotations

import os
import shutil

#: Fixed, not ``tempfile.mkdtemp()``: every Gunicorn worker forked from this
#: master must agree on the same directory, and it is wiped/recreated below
#: on every master start regardless of prior contents, so a fixed path is
#: both simpler and sufficient.
_DEFAULT_MULTIPROC_DIR = "/tmp/supportpilot-prometheus-multiproc"

# Conservative, explicitly-documented defaults — never a workstation/build-host
# CPU-derived count (section 39). Raise via environment for a real deployment
# sized to its own traffic/hardware.
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
timeout = int(os.environ.get("WEB_TIMEOUT_SECONDS", "30"))
# Bounded grace period for in-flight requests to finish after SIGTERM before
# Gunicorn escalates to SIGKILL (section 11: graceful shutdown must not
# require SIGKILL under normal operation).
graceful_timeout = int(os.environ.get("WEB_GRACEFUL_TIMEOUT_SECONDS", "30"))
keepalive = int(os.environ.get("WEB_KEEPALIVE_SECONDS", "5"))
# Explicit stdout/stderr logging — container runtimes capture these directly;
# no local log file is ever required for this process to operate.
accesslog = "-"
errorlog = "-"


def on_starting(server):  # noqa: ARG001 - required Gunicorn hook signature
    from observability.prometheus_paths import assert_safe_multiprocess_dir

    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR", _DEFAULT_MULTIPROC_DIR)
    # Phase 11 Block 5 (section 23-24): a misconfigured value here (empty,
    # "/", a drive root, the checkout/home directory) must fail Gunicorn's
    # own startup loudly rather than silently ``rmtree`` something
    # catastrophic — this intentionally raises, uncaught, so the master
    # process refuses to start.
    assert_safe_multiprocess_dir(multiproc_dir)
    shutil.rmtree(multiproc_dir, ignore_errors=True)
    os.makedirs(multiproc_dir, exist_ok=True)
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir


def child_exit(server, worker):  # noqa: ARG001 - required Gunicorn hook signature
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
