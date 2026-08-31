"""Correlation ID and structured request logging middleware."""

import logging
import time

from .correlation import correlation_scope
from .request_id import validate_request_id

logger = logging.getLogger("supportpilot")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware:
    """Attach a stable correlation/request ID to every request and response.

    Reuses an inbound ``X-Request-ID`` header when present and safe
    (:func:`common.request_id.validate_request_id` — bounded, ASCII-safe,
    section 2 of the Block 2 remediation brief) so requests can be
    correlated across services; a missing or unsafe value generates a fresh
    UUID4 instead, never rejecting the request and never echoing the unsafe
    value anywhere.

    Binds ``request.request_id`` into :mod:`common.correlation`'s scope
    (Phase 11 Block 2) for the lifetime of ``get_response`` — every log line
    emitted while the request is being handled, including any
    ``transaction.on_commit`` Celery dispatch it triggers, therefore already
    carries this id without any call site passing it explicitly.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = validate_request_id(request.META.get("HTTP_X_REQUEST_ID"))
        with correlation_scope(request.request_id):
            response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request.request_id
        return response


class StructuredLoggingMiddleware:
    """Emit one structured log line per completed request.

    Must run after :class:`RequestIdMiddleware` so ``request.request_id`` is
    already populated.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "request_completed",
            extra={
                "request_id": getattr(request, "request_id", None),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
        return response
