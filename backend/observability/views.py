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

from django.conf import settings
from django.http import HttpResponse

from .metrics import METRICS_CONTENT_TYPE, render_metrics

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
    return HttpResponse(render_metrics(), content_type=METRICS_CONTENT_TYPE)
