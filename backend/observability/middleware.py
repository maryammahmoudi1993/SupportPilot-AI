"""HTTP request metrics middleware (Phase 11 Block 1).

Placed after ``common.middleware.StructuredLoggingMiddleware`` in
``MIDDLEWARE`` so a metrics-recording bug can never prevent — or even run
before — the existing request-id/structured-logging behavior (section 30:
observability must never affect business/request handling; if it fails, the
request must still complete normally).
"""

from __future__ import annotations

import logging
import time

from . import tracing
from .metrics import observe_http_request

logger = logging.getLogger("supportpilot")

#: Route names excluded from HTTP request metrics entirely (section 58): the
#: metrics endpoint itself must not generate an ever-growing self-referential
#: entry in its own scrape output every time it is scraped.
_EXCLUDED_ROUTE_NAMES = frozenset({"metrics"})

#: Raw path (not route name — unresolved at span-start time, before
#: ``get_response`` runs URL resolution) excluded from *tracing* entirely
#: (Block 2 remediation section 31): a scraper polling ``/metrics/`` every
#: few seconds must not generate a matching flood of spans. ``/health/`` and
#: ``/ready/`` are deliberately still traced — cheap, and readiness must not
#: be made to *depend* on tracing (tracing already fails open), but there is
#: no matching noise concern that would justify excluding them too.
_TRACING_EXCLUDED_PATHS = frozenset({"/metrics/"})


def _route_label(request) -> str:
    """A bounded route identifier for the ``route`` metric label (section
    10): the resolved URL name from Django's URLconf, never the raw request
    path. A path that never resolved to a view (a 404, or an attacker
    path-scanning probe) collapses to the single value ``"unmatched"``
    rather than creating one time series per probed path — this is itself a
    cardinality-attack defense (section 47), not just a naming convenience.
    """
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is None or not resolver_match.view_name:
        return "unmatched"
    return str(resolver_match.view_name)


class MetricsMiddleware:
    """Records one HTTP request/duration observation per completed request.

    Failure isolation (section 30, 51): any exception raised while recording
    a metric is caught and logged, never allowed to fail the actual HTTP
    response.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        route = _route_label(request)
        if route in _EXCLUDED_ROUTE_NAMES:
            return response
        try:
            observe_http_request(
                method=request.method,
                route=route,
                status_code=response.status_code,
                duration_seconds=time.monotonic() - start,
            )
        except Exception:  # noqa: BLE001 - telemetry must fail open
            logger.warning("http_metrics_recording_failed", extra={"event": "metrics_error"})
        return response


def _w3c_carrier(request) -> dict[str, str]:
    """Only the two W3C trace-context headers (section 9: never capture
    headers wholesale), read straight off the raw WSGI environ into the
    plain-dict carrier OpenTelemetry's propagator expects."""
    carrier = {}
    if "HTTP_TRACEPARENT" in request.META:
        carrier["traceparent"] = request.META["HTTP_TRACEPARENT"]
    if "HTTP_TRACESTATE" in request.META:
        carrier["tracestate"] = request.META["HTTP_TRACESTATE"]
    return carrier


class TracingMiddleware:
    """Creates one server span per HTTP request (Phase 11 Block 2, Part B).

    Parented to a valid inbound W3C ``traceparent``/``tracestate`` when
    present (section 12); a malformed or absent one safely starts a fresh
    local trace instead of failing the request (section 13) — extraction
    itself already fails open inside ``observability.tracing``.

    Placed immediately after ``RequestIdMiddleware`` and before
    ``StructuredLoggingMiddleware`` so ``trace_id``/``span_id`` are already
    bound (via ``observability.tracing.TraceContextLogFilter``) for every
    log line the rest of the request emits, including
    ``StructuredLoggingMiddleware``'s own completion line.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in _TRACING_EXCLUDED_PATHS:
            return self.get_response(request)

        parent_context = tracing.extract_context(_w3c_carrier(request))
        with tracing.server_span("HTTP request", parent_context=parent_context) as span:
            try:
                response = self.get_response(request)
            except Exception:
                tracing.mark_span_error(span)
                raise
            tracing.finalize_server_span(
                span,
                method=request.method,
                route=_route_label(request),
                status_code=response.status_code,
            )
            return response
