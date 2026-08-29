"""Vendor-neutral distributed tracing boundary (Phase 11 Block 2 Part B,
extended by Block 3 with a real OTLP exporter).

Everything OpenTelemetry-specific in this application goes through this one
module (section 7's "one call site" principle, applied here the same way it
is already applied to metrics in ``observability/metrics.py`` and to
correlation ids in ``common/correlation.py``): tracer/provider lifecycle,
safe span creation, trace/span id access, and W3C ``traceparent``/
``tracestate`` inject/extract. No other module imports ``opentelemetry``
directly.

Design choices, matching ADR 0009's original trade-off note that adding
OpenTelemetry later "does not foreclose" on the metrics decision:

* **Exporter is opt-in and explicit, never a silent default.** Block 2
  shipped a ``TracerProvider`` with no processor — spans were created with
  real, correctly-propagated ``trace_id``/``span_id`` but had nowhere to
  go. Block 3 adds an OTLP/HTTP exporter (``BatchSpanProcessor`` +
  ``OTLPSpanExporter``), attached *only* when ``OBSERVABILITY_OTLP_ENDPOINT``
  is actually configured. Endpoint absent (the default) is deliberate,
  documented local/no-export mode, not a degraded or accidental state — no
  remote collector is ever silently chosen.
* **Fails open, always.** Every public function in this module catches its
  own OpenTelemetry-specific failures and degrades to "no span"/"no
  context" rather than raising — mirroring
  ``observability.metrics``/``common.tasks``'s existing failure-isolation
  guarantee. A tracing bug must never be a business-request or task-
  execution outage.
* **Raw exception text is never recorded onto a span.** ``record_exception``
  is deliberately never used with an application/external exception object
  (section 21 — a hard security gate): span status is set from safe,
  server-owned outcome labels only (HTTP status code, Celery task outcome),
  never from ``str(exc))``/``repr(exc)``/provider response text.
* **Lazy, idempotent, process-safe initialization.** The ``TracerProvider``
  is built on first use, guarded by a lock, and cached on this module — not
  via OpenTelemetry's process-global ``trace.set_tracer_provider`` (which
  logs a warning and refuses a second real provider). This is what makes
  initialization safe to call from any process (Gunicorn worker, Celery
  worker, a management command, a test) in any order, and what lets tests
  swap in an in-memory exporter via :func:`use_provider_for_tests` without
  fighting OpenTelemetry's own single-global-provider restriction.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager

from django.conf import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract as _otel_extract
from opentelemetry.propagate import inject as _otel_inject
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace.status import Status, StatusCode

logger = logging.getLogger("supportpilot")

__all__ = [
    "get_tracer_provider",
    "get_tracer",
    "server_span",
    "task_span",
    "mark_span_error",
    "finalize_server_span",
    "finalize_task_span",
    "extract_context",
    "inject_context",
    "get_trace_id",
    "get_span_id",
    "use_provider_for_tests",
    "TraceContextLogFilter",
]

# W3C trace-context only — deliberately not OpenTelemetry's default
# composite propagator, which also carries "baggage" (arbitrary
# application-defined key/value pairs). This application has no use for
# baggage, and it is exactly the kind of unbounded, easily-misused-for-
# business-data channel section 4/9 of the remediation brief warns against
# for spans generally. Configuring this is pure in-memory state — safe to
# do unconditionally at import time regardless of whether tracing is
# enabled.
set_global_textmap(TraceContextTextMapPropagator())

_provider: TracerProvider | None = None
_provider_lock = threading.Lock()


def _build_provider() -> TracerProvider:
    resource = Resource.create({"service.name": settings.OBSERVABILITY_SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    endpoint = settings.OBSERVABILITY_OTLP_ENDPOINT
    if endpoint:
        # Phase 11 Block 3 (section 8-11): the one place a real exporter is
        # attached. Explicit local/no-export mode (endpoint absent) is the
        # default and is not an error — see the module docstring's
        # "Amendment" note and ADR 0009. Construction failure (a malformed
        # endpoint URL, for instance) must not prevent the provider itself
        # from existing — spans still work locally, just unexported —
        # matching this module's fail-open guarantee everywhere else.
        try:
            exporter = OTLPSpanExporter(endpoint=endpoint)
            # BatchSpanProcessor buffers/exports on its own background
            # thread — never synchronously on the request/task thread
            # (section 10/45) — and every export call is independently
            # wrapped by OTel's own exporter (never raises into the
            # caller); collector-unavailable/timeout/non-2xx responses are
            # swallowed there, not here. Constructed lazily, per-process,
            # the same way the provider itself is (section 10: never at
            # Gunicorn pre-fork, never depending on Gunicorn from a Celery
            # worker) — this function is only ever called from
            # ``get_tracer_provider``'s lazy, per-process path.
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:  # noqa: BLE001 - telemetry must fail open
            logger.warning("tracing_otlp_exporter_init_failed", extra={"event": "tracing_error"})
    return provider


def get_tracer_provider() -> TracerProvider:
    """The process-local ``TracerProvider``, built lazily on first use.

    Idempotent and process-safe (section 7): concurrent first callers race
    on ``_provider_lock``, not on OpenTelemetry's own global provider
    setter, so this never triggers "Overriding of current TracerProvider is
    not allowed". Each process (a Gunicorn worker, a Celery worker, a
    management command, a test) gets its own provider the first time it
    actually needs one — nothing is initialized at import time or at
    Gunicorn master pre-fork (section 32: no exporter, so no fork-safety
    concern to design around; section 33: a Celery worker never depends on
    Gunicorn having initialized anything).
    """
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = _build_provider()
    return _provider


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("supportpilot", tracer_provider=get_tracer_provider())


def use_provider_for_tests(provider: TracerProvider | None) -> None:
    """Test-only: replace the cached provider — typically one wired to an
    in-memory exporter so a test can assert on finished spans — or pass
    ``None`` to drop back to lazy-rebuild-on-next-use. Never used by
    application code; correctness must never depend on this being called
    (or on the order tests happen to run in)."""
    global _provider
    _provider = provider


# ---------------------------------------------------------------------------
# W3C context propagation
# ---------------------------------------------------------------------------


def extract_context(carrier: Mapping[str, str]):
    """Parse an inbound W3C ``traceparent``/``tracestate`` carrier via
    OpenTelemetry's own propagator — never hand-rolled parsing (section 12).
    A malformed or absent carrier safely yields a context with no valid
    parent span (OpenTelemetry's own ``extract`` already tolerates
    malformed input); this never raises and never reflects the raw
    malformed value anywhere. Returns ``None`` when tracing is disabled."""
    if not settings.OBSERVABILITY_TRACING_ENABLED:
        return None
    try:
        return _otel_extract(carrier)
    except Exception:  # noqa: BLE001 - telemetry must fail open (section 13)
        logger.warning("tracing_context_extract_failed", extra={"event": "tracing_error"})
        return None


def inject_context(carrier: MutableMapping[str, str]) -> None:
    """Write the active span's W3C context into ``carrier`` in place. A
    no-op (not an error) when tracing is disabled or there is no active
    span with a valid context — the propagator itself already handles
    that. Never raises (section 15/25: injection failure must never block
    publication of the thing being traced)."""
    if not settings.OBSERVABILITY_TRACING_ENABLED:
        return
    try:
        _otel_inject(carrier)
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("tracing_context_inject_failed", extra={"event": "tracing_error"})


# ---------------------------------------------------------------------------
# Safe span creation
# ---------------------------------------------------------------------------


@contextmanager
def _safe_span(
    name: str,
    *,
    kind: SpanKind,
    parent_context=None,
    attributes: Mapping[str, str] | None = None,
) -> Iterator[Span | None]:
    """Shared implementation behind :func:`server_span`/:func:`task_span`.

    Yields ``None`` — never raises — whenever tracing is disabled or span
    creation itself fails (section 24/26: a broken tracing helper must
    never prevent the HTTP request or Celery task it wraps from running).
    The span is always ended with no exception info forwarded
    (``__exit__(None, None, None)``): OpenTelemetry's own automatic
    exception recording (``record_exception``) is thereby never reached
    regardless of ``record_exception=False`` below — the caller's business
    exception, if any, is left to propagate through this generator
    untouched; only span *end* is guarded, not the caller's own body.
    """
    if not settings.OBSERVABILITY_TRACING_ENABLED:
        yield None
        return
    try:
        span_cm = get_tracer().start_as_current_span(
            name,
            context=parent_context,
            kind=kind,
            attributes=dict(attributes or {}),
            record_exception=False,
            set_status_on_exception=False,
        )
        span = span_cm.__enter__()
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("tracing_span_start_failed", extra={"event": "tracing_error"})
        yield None
        return
    try:
        yield span
    finally:
        try:
            span_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - telemetry must fail open
            logger.warning("tracing_span_end_failed", extra={"event": "tracing_error"})


def server_span(name: str, *, parent_context=None):
    """One HTTP server span per request (section 8), parented to a valid
    inbound W3C context when present."""
    return _safe_span(name, kind=SpanKind.SERVER, parent_context=parent_context)


def task_span(task_name: str, *, headers: Mapping[str, str] | None = None):
    """One Celery consumer span per task execution (section 16), parented
    to whatever W3C context :func:`inject_context` placed into the message
    headers at publish time (section 15) — extraction failure yields a
    fresh, parentless span rather than blocking task execution (section
    26)."""
    parent_context = extract_context(headers or {})
    return _safe_span(
        f"celery.task {task_name}",
        kind=SpanKind.CONSUMER,
        parent_context=parent_context,
        attributes={"celery.task_name": task_name},
    )


def mark_span_error(span: Span | None) -> None:
    """Safe failure status only — never a raw exception message (section
    21/23)."""
    if span is None:
        return
    try:
        span.set_status(Status(StatusCode.ERROR))
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("tracing_span_status_failed", extra={"event": "tracing_error"})


def finalize_server_span(span: Span | None, *, method: str, route: str, status_code: int) -> None:
    """Bounded HTTP attributes only (section 9) — never a raw path, query
    string, header, or body. ``route`` must already be the normalized URL
    name (section 8), not a raw path — callers are responsible for that
    normalization, exactly like ``observability.metrics.observe_http_request``
    already requires of its own ``route`` argument."""
    if span is None:
        return
    try:
        span.update_name(f"HTTP {method} {route}")
        span.set_attribute("http.request.method", method)
        span.set_attribute("http.route", route)
        span.set_attribute("http.response.status_code", status_code)
        from common.correlation import get_request_id

        request_id = get_request_id()
        if request_id:
            span.set_attribute("supportpilot.request_id", request_id)
        span.set_status(Status(StatusCode.ERROR if status_code >= 500 else StatusCode.OK))
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("tracing_span_finalize_failed", extra={"event": "tracing_error"})


#: Bounded outcome values only (section 19) — mirrors
#: ``observability.metrics``'s own ``_CELERY_OUTCOMES``.
_TASK_OUTCOMES = frozenset({"success", "failure", "retry"})


def finalize_task_span(span: Span | None, *, outcome: str) -> None:
    """Bounded task attributes only (section 18) — never args/kwargs,
    payload, or any business value."""
    if span is None:
        return
    try:
        outcome_label = outcome if outcome in _TASK_OUTCOMES else "failure"
        span.set_attribute("supportpilot.task_outcome", outcome_label)
        span.set_status(Status(StatusCode.OK if outcome_label == "success" else StatusCode.ERROR))
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("tracing_span_finalize_failed", extra={"event": "tracing_error"})


# ---------------------------------------------------------------------------
# Trace/span id access (section 10/11) — kept semantically distinct from
# common.correlation.get_request_id/get_correlation_id.
# ---------------------------------------------------------------------------


def get_trace_id() -> str | None:
    """32 lowercase-hex-character trace id of the current span, or
    ``None`` when tracing is disabled or there is no active valid span
    (section 11) — never raises."""
    if not settings.OBSERVABILITY_TRACING_ENABLED:
        return None
    try:
        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return None
        return format(span_context.trace_id, "032x")
    except Exception:  # noqa: BLE001 - telemetry must fail open
        return None


def get_span_id() -> str | None:
    """16 lowercase-hex-character span id of the current span, or ``None``
    (section 11) — never raises."""
    if not settings.OBSERVABILITY_TRACING_ENABLED:
        return None
    try:
        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            return None
        return format(span_context.span_id, "016x")
    except Exception:  # noqa: BLE001 - telemetry must fail open
        return None


class TraceContextLogFilter(logging.Filter):
    """Attach ``trace_id``/``span_id`` to every log record (section 28),
    mirroring ``common.correlation.CorrelationIdLogFilter``'s
    ``request_id`` injection. Wired into ``LOGGING["filters"]`` in
    ``config/settings.py`` alongside it. Never logs raw ``traceparent``/
    ``tracestate`` header values (section 28/29) — only the derived,
    bounded hex ids."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.trace_id = get_trace_id() or ""
            record.span_id = get_span_id() or ""
        except Exception:  # noqa: BLE001 - logging must never break
            record.trace_id = ""
            record.span_id = ""
        return True
