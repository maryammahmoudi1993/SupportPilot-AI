"""Shared throttle machinery (Phase 14, Section 18-19).

Every scoped throttle in the application is backed by the same
Redis-backed Django cache (``config.settings.CACHES["default"]``), so
throttle state is already shared across every web/worker process — there
is no separate distributed-throttle implementation to maintain here.

What *is* centralized here is cache-outage behavior: DRF's
``ScopedRateThrottle`` calls straight into the configured cache, and a
Redis exception during that call is not a DRF ``APIException`` — left
alone, it propagates as an unhandled exception and becomes a generic,
undifferentiated 500 (safe, but not a deliberate contract). For every
high-risk category named in Section 19 (auth, public chat, public signed
ingress, agent/evaluation execution, sensitive mutations) a cache outage
instead fails closed with a bounded, stable ``service_unavailable`` 503 —
never a raw stack trace, and never mistaken for an actual `rate_limited`
rejection.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle

from common.exceptions import SafeAPIError

logger = logging.getLogger("supportpilot")


class ThrottleCacheUnavailable(SafeAPIError):
    """The throttle's backing cache could not be reached. Distinct from an
    actual rate-limit rejection (``Throttled``/``rate_limited``) — this is
    an infrastructure failure, not a client exceeding its quota. Reuses the
    stable ``{"error": {...}}`` envelope like every other application
    error (Section 19-20)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("Service temporarily unavailable.", code="service_unavailable")


class SafeScopedRateThrottle(ScopedRateThrottle):
    """``ScopedRateThrottle`` that fails closed and safely on a cache
    outage, instead of letting the underlying Redis exception (connection
    strings, host, port included) propagate as an unhandled 500."""

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except ThrottleCacheUnavailable:
            raise
        except Exception as exc:  # cache/Redis outage — never a raw 500
            logger.exception("throttle_cache_unavailable")
            raise ThrottleCacheUnavailable() from exc
