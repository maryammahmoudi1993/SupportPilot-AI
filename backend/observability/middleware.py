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

from .metrics import observe_http_request

logger = logging.getLogger("supportpilot")

#: Route names excluded from HTTP request metrics entirely (section 58): the
#: metrics endpoint itself must not generate an ever-growing self-referential
#: entry in its own scrape output every time it is scraped.
_EXCLUDED_ROUTE_NAMES = frozenset({"metrics"})


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
