"""HTTP response classification (Phase 10 Block 3, section 30, 57-59)."""

from __future__ import annotations

import pytest

from webhooks.classification import classify_http_status


@pytest.mark.parametrize("status_code", [408, 425, 429, 500, 502, 503, 599])
def test_retryable_status_codes(status_code):
    retryable, code = classify_http_status(status_code)
    assert retryable is True
    assert code == f"webhook_http_{status_code}"


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 410, 422])
def test_terminal_status_codes(status_code):
    retryable, code = classify_http_status(status_code)
    assert retryable is False
    assert code == f"webhook_http_{status_code}"
