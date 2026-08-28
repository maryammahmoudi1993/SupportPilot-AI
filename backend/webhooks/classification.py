"""HTTP response classification for outbound webhook delivery (Phase 10
Block 3, section 30).

3xx never reaches this function — ``webhooks.transport.send_pinned_request``
rejects redirects itself before returning (section 27). 2xx is handled by
the caller directly; this only classifies a non-2xx status already known to
be outside the redirect range.
"""

from __future__ import annotations

#: 408 (request timeout), 425 (too early), and 429 (rate limited) are
#: retryable even though outside the 5xx range — the same treatment
#: ``integrations.errors`` already gives rate-limit/timeout conditions.
RETRYABLE_4XX_STATUS_CODES = frozenset({408, 425, 429})


def classify_http_status(status_code: int) -> tuple[bool, str]:
    """Returns ``(retryable, safe_error_code)`` for a non-2xx, non-3xx HTTP
    status (section 30):

    * 408 / 425 / 429 -> retryable
    * 500-599 -> retryable
    * everything else (most 4xx) -> terminal
    """
    safe_error_code = f"webhook_http_{status_code}"
    if status_code in RETRYABLE_4XX_STATUS_CODES or 500 <= status_code <= 599:
        return True, safe_error_code
    return False, safe_error_code
