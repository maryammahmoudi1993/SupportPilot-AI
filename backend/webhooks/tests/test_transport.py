"""Pinned outbound transport tests (Phase 10 Block 3, section 24-31, 54-56,
60). Every test here uses a fake connection pool injected via
``pool_factory`` — never a real socket/network call — while still proving
*what the transport asks urllib3 to do*: connect to the pre-approved IP,
verify TLS against the original hostname, never re-resolve DNS.
"""

from __future__ import annotations

import pytest
import urllib3

from webhooks.errors import WebhookRedirectRejectedError, WebhookTimeoutError, WebhookTlsError
from webhooks.transport import _build_pool, send_pinned_request


class _FakeResponse:
    def __init__(self, status: int):
        self.status = status

    def read(self, amt=None, decode_content=None):
        return b""

    def release_conn(self):
        pass


class _FakePool:
    """Captures exactly what ``send_pinned_request`` passes to
    ``pool.request(...)`` and what ``_build_pool``-equivalent construction
    args it received, without opening any socket."""

    last_construction_kwargs: dict | None = None

    def __init__(self, *, status=204, raise_exc=None, **construction_kwargs):
        self.status = status
        self.raise_exc = raise_exc
        self.requests: list[dict] = []
        type(self).last_construction_kwargs = construction_kwargs

    def request(self, method, url, *, body, headers, **kwargs):
        self.requests.append(
            {"method": method, "url": url, "body": body, "headers": headers, "kwargs": kwargs}
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        return _FakeResponse(self.status)

    def close(self):
        pass


def _factory(*, status=204, raise_exc=None):
    def factory(*, scheme, ip, port, hostname):
        return _FakePool(
            status=status, raise_exc=raise_exc, scheme=scheme, ip=ip, port=port, hostname=hostname
        )

    return factory


# ---------------------------------------------------------------------------
# DNS-rebinding-safe pinning proof (section 54, release-critical)
# ---------------------------------------------------------------------------


def test_transport_connects_to_approved_ip_not_hostname(monkeypatch):
    """The pool is constructed with the approved IP as its connect target
    — never the original hostname — so no DNS resolution by the HTTP
    client itself can occur for this request."""

    def _fail_if_dns_called(*args, **kwargs):
        raise AssertionError("transport must never resolve DNS itself")

    monkeypatch.setattr("socket.getaddrinfo", _fail_if_dns_called)

    captured = {}

    def factory(*, scheme, ip, port, hostname):
        captured.update(scheme=scheme, ip=ip, port=port, hostname=hostname)
        return _FakePool(status=204)

    result = send_pinned_request(
        scheme="https",
        ip="93.184.216.34",
        port=443,
        hostname="webhook.example.com",
        path_and_query="/hook",
        headers={"X-Test": "1"},
        body=b"{}",
        pool_factory=factory,
    )
    assert result.status_code == 204
    assert captured["ip"] == "93.184.216.34"
    assert captured["hostname"] == "webhook.example.com"


def test_transport_preserves_original_hostname_for_sni_and_host_header():
    """Section 24-25: the original hostname is what TLS SNI/certificate
    verification uses (proven at the pool-construction level here — the
    real urllib3 ``server_hostname``/``assert_hostname`` wiring is
    exercised directly against real urllib3 in
    ``test_real_pool_construction_pins_ip_and_preserves_hostname`` below)
    and what the ``Host`` header carries."""
    pool_holder = {}

    def factory(*, scheme, ip, port, hostname):
        pool = _FakePool(status=204, scheme=scheme, ip=ip, port=port, hostname=hostname)
        pool_holder["pool"] = pool
        return pool

    send_pinned_request(
        scheme="https",
        ip="93.184.216.34",
        port=443,
        hostname="webhook.example.com",
        path_and_query="/hook",
        headers={},
        body=b"{}",
        pool_factory=factory,
    )
    sent = pool_holder["pool"].requests[0]
    assert sent["headers"]["Host"] == "webhook.example.com"


def test_real_pool_construction_pins_ip_and_preserves_hostname(settings):
    """Exercises the *real* ``_build_pool`` against real urllib3 (no
    network call — pool construction only) to prove the actual production
    wiring, not just the fake's contract: the pool's connect target is the
    IP, and ``server_hostname``/``assert_hostname`` are the original
    hostname (section 54)."""
    pool = _build_pool(scheme="https", ip="93.184.216.34", port=443, hostname="webhook.example.com")
    try:
        assert isinstance(pool, urllib3.HTTPSConnectionPool)
        assert pool.host == "93.184.216.34"
        assert pool.port == 443
        assert pool.conn_kw.get("server_hostname") == "webhook.example.com"
        assert pool.assert_hostname == "webhook.example.com"
    finally:
        pool.close()


def test_redirect_is_never_followed_and_rejected(settings):
    with pytest.raises(WebhookRedirectRejectedError):
        send_pinned_request(
            scheme="https",
            ip="93.184.216.34",
            port=443,
            hostname="webhook.example.com",
            path_and_query="/hook",
            headers={},
            body=b"{}",
            pool_factory=_factory(status=302),
        )


def test_redirect_request_never_passes_redirect_true_to_pool():
    pool_holder = {}

    def factory(*, scheme, ip, port, hostname):
        pool = _FakePool(status=302)
        pool_holder["pool"] = pool
        return pool

    with pytest.raises(WebhookRedirectRejectedError):
        send_pinned_request(
            scheme="https",
            ip="1.2.3.4",
            port=443,
            hostname="h.example.com",
            path_and_query="/",
            headers={},
            body=b"{}",
            pool_factory=factory,
        )
    assert pool_holder["pool"].requests[0]["kwargs"]["redirect"] is False


def test_success_status_returned():
    result = send_pinned_request(
        scheme="https",
        ip="93.184.216.34",
        port=443,
        hostname="webhook.example.com",
        path_and_query="/hook",
        headers={},
        body=b"{}",
        pool_factory=_factory(status=200),
    )
    assert result.status_code == 200
    assert result.latency_ms >= 0


def test_http_error_status_returned_without_raising():
    result = send_pinned_request(
        scheme="https",
        ip="93.184.216.34",
        port=443,
        hostname="webhook.example.com",
        path_and_query="/hook",
        headers={},
        body=b"{}",
        pool_factory=_factory(status=500),
    )
    assert result.status_code == 500


def test_connect_timeout_maps_to_safe_timeout_error():
    with pytest.raises(WebhookTimeoutError):
        send_pinned_request(
            scheme="https",
            ip="93.184.216.34",
            port=443,
            hostname="webhook.example.com",
            path_and_query="/hook",
            headers={},
            body=b"{}",
            pool_factory=_factory(raise_exc=urllib3.exceptions.ConnectTimeoutError("timed out")),
        )


def test_read_timeout_maps_to_safe_timeout_error():
    with pytest.raises(WebhookTimeoutError):
        send_pinned_request(
            scheme="https",
            ip="93.184.216.34",
            port=443,
            hostname="webhook.example.com",
            path_and_query="/hook",
            headers={},
            body=b"{}",
            pool_factory=_factory(
                raise_exc=urllib3.exceptions.ReadTimeoutError(None, "/hook", "timed out")
            ),
        )


def test_tls_error_is_never_retried_and_never_a_timeout():
    with pytest.raises(WebhookTlsError) as exc_info:
        send_pinned_request(
            scheme="https",
            ip="93.184.216.34",
            port=443,
            hostname="webhook.example.com",
            path_and_query="/hook",
            headers={},
            body=b"{}",
            pool_factory=_factory(raise_exc=urllib3.exceptions.SSLError("cert verify failed")),
        )
    assert exc_info.value.retryable is False


def test_real_pool_construction_uses_plain_http_pool_when_scheme_is_http():
    pool = _build_pool(scheme="http", ip="93.184.216.34", port=80, hostname="webhook.example.com")
    try:
        assert type(pool) is urllib3.HTTPConnectionPool
        assert pool.host == "93.184.216.34"
    finally:
        pool.close()


def test_connection_refused_maps_to_safe_connection_error():
    from webhooks.errors import WebhookConnectionError

    with pytest.raises(WebhookConnectionError):
        send_pinned_request(
            scheme="https",
            ip="93.184.216.34",
            port=443,
            hostname="webhook.example.com",
            path_and_query="/hook",
            headers={},
            body=b"{}",
            pool_factory=_factory(
                raise_exc=urllib3.exceptions.NewConnectionError(None, "connection refused")
            ),
        )


def test_connection_reset_maps_to_safe_connection_error():
    from webhooks.errors import WebhookConnectionError

    with pytest.raises(WebhookConnectionError):
        send_pinned_request(
            scheme="https",
            ip="93.184.216.34",
            port=443,
            hostname="webhook.example.com",
            path_and_query="/hook",
            headers={},
            body=b"{}",
            pool_factory=_factory(raise_exc=urllib3.exceptions.ProtocolError("connection reset")),
        )


def test_unrecognized_transport_error_fails_closed():
    from webhooks.errors import WebhookUnexpectedTransportError

    with pytest.raises(WebhookUnexpectedTransportError):
        send_pinned_request(
            scheme="https",
            ip="93.184.216.34",
            port=443,
            hostname="webhook.example.com",
            path_and_query="/hook",
            headers={},
            body=b"{}",
            pool_factory=_factory(raise_exc=urllib3.exceptions.HTTPError("something unrecognized")),
        )
