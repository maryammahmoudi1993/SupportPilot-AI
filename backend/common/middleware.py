"""Correlation ID and structured request logging middleware."""

import logging
import time
import uuid

logger = logging.getLogger("supportpilot")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware:
    """Attach a stable correlation/request ID to every request and response.

    Reuses an inbound ``X-Request-ID`` header when present so requests can be
    correlated across services; otherwise generates a new UUID4.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.META.get("HTTP_X_REQUEST_ID") or str(uuid.uuid4())
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
