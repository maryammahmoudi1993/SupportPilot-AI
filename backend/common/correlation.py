"""Correlation-ID propagation (Phase 11 Block 2).

A single ``contextvars.ContextVar`` is the source of truth for "what
correlation id is the current thread/task working under" — bound once at
the boundary that owns the id (``RequestIdMiddleware`` for an HTTP request,
``common.tasks.CorrelatedTask`` for a Celery task) and read everywhere else
via :func:`get_correlation_id`, including by :class:`CorrelationIdLogFilter`
so every structured log line emitted while the scope is active carries it
automatically — no call site has to thread it through ``extra=`` by hand.

This is deliberately the *only* thing this module does: it carries a single
bounded, server-owned UUID string across an async boundary, never business
payload (section 30 of the observability doc: telemetry must never become
part of business correctness, and must never leak unbounded data).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    """A fresh id for a boundary that has no inbound correlation id to
    reuse (e.g. a Beat-triggered sweep, or a task invoked directly without
    going through :class:`common.tasks.CorrelatedTask`'s normal dispatch
    path)."""
    return str(uuid.uuid4())


def get_correlation_id() -> str | None:
    """The correlation id bound by the current scope, if any."""
    return _correlation_id.get()


@contextmanager
def correlation_scope(correlation_id: str | None) -> Iterator[None]:
    """Bind ``correlation_id`` for the duration of the ``with`` block,
    restoring whatever was bound before on exit (never leaking across
    requests/tasks sharing a worker thread or greenlet)."""
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)


class CorrelationIdLogFilter(logging.Filter):
    """Attach the current scope's correlation id to every log record.

    Wired into ``LOGGING["filters"]`` in ``config/settings.py`` and attached
    to the ``console`` handler; ``common.logging.JsonFormatter`` then emits
    whatever it finds as a normal top-level ``correlation_id`` field. A
    record produced outside any bound scope gets ``""`` rather than being
    left without the key, so downstream log queries can rely on the field
    always being present.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or ""
        return True
