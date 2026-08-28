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
* ``child_exit`` runs in the master whenever a worker process exits, and
  tells ``prometheus_client`` to discard that worker's mmap files
  immediately — without this, a scrape after a worker restart (a graceful
  reload, an OOM-killed worker Gunicorn replaces) would keep double-counting
  a dead process's last-known values forever.

Only ``gunicorn`` (the production web process) uses this file — Celery
workers and ``manage.py`` commands are deliberately left in
``prometheus_client``'s default single-process mode (no
``PROMETHEUS_MULTIPROC_DIR`` set for them), matching section 64's
requirement that ordinary local/dev/test/management-command runs stay
simple and need no multiprocess directory to exist at all.
"""

from __future__ import annotations

import os
import shutil

#: Fixed, not ``tempfile.mkdtemp()``: every Gunicorn worker forked from this
#: master must agree on the same directory, and it is wiped/recreated below
#: on every master start regardless of prior contents, so a fixed path is
#: both simpler and sufficient.
_DEFAULT_MULTIPROC_DIR = "/tmp/supportpilot-prometheus-multiproc"


def on_starting(server):  # noqa: ARG001 - required Gunicorn hook signature
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR", _DEFAULT_MULTIPROC_DIR)
    shutil.rmtree(multiproc_dir, ignore_errors=True)
    os.makedirs(multiproc_dir, exist_ok=True)
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = multiproc_dir


def child_exit(server, worker):  # noqa: ARG001 - required Gunicorn hook signature
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
