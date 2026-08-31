"""Metrics scrape endpoint (Phase 11 Block 1, section 26-28).

Deliberately a plain Django view, not a DRF ``APIView``: this is deployment
infrastructure, not a product/tenant API, and must never be introspected by
drf-spectacular into the public OpenAPI schema (section 59) or reachable
through DRF's JWT/session authentication or workspace RBAC (section 26-27) —
a single server-owned bearer token is the only door.

Every denial path — disabled, missing token, wrong token — returns the same
generic 404 (section 27: "non-sensitive denial... do not leak whether
another valid token exists").
"""

from __future__ import annotations

import hmac
import logging

from django.conf import settings
from django.http import HttpResponse

from .metrics import METRICS_CONTENT_TYPE, refresh_delivery_backlog_gauges, render_metrics

logger = logging.getLogger("supportpilot")

_DENIED_RESPONSE_KWARGS = {"content": b"Not Found", "status": 404, "content_type": "text/plain"}


def _token_is_valid(request) -> bool:
    configured_token = settings.OBSERVABILITY_METRICS_TOKEN
    if not configured_token:
        return False
    header = request.META.get("HTTP_AUTHORIZATION", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    presented_token = header[len(prefix) :]
    # Constant-time comparison (section 27) — a naive ``==`` would let an
    # attacker recover the token one byte at a time via response-timing
    # measurements.
    return hmac.compare_digest(presented_token, configured_token)


def metrics_view(request):
    if not settings.OBSERVABILITY_METRICS_ENABLED:
        return HttpResponse(**_DENIED_RESPONSE_KWARGS)
    if not _token_is_valid(request):
        return HttpResponse(**_DENIED_RESPONSE_KWARGS)
    # Phase 11 Block 4 (section 20-21): the one deliberate scrape point that
    # recomputes the DB-derived delivery backlog gauges — never the Celery
    # worker's own metrics listener (``config/celery_metrics.py``), which
    # calls ``render_metrics()`` directly with no DB query of its own. Fails
    # open internally (``refresh_delivery_backlog_gauges``'s own try/except)
    # so a PostgreSQL error here degrades those specific gauges to their
    # last-known value, never the whole scrape.
    try:
        refresh_delivery_backlog_gauges()
    except Exception:  # noqa: BLE001 - telemetry must fail open
        logger.warning("delivery_backlog_gauge_refresh_failed", extra={"event": "metrics_error"})
    return HttpResponse(render_metrics(), content_type=METRICS_CONTENT_TYPE)
