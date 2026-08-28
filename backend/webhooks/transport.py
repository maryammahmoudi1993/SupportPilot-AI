"""SSRF-safe, DNS-rebinding-safe outbound webhook transport (Phase 10
Block 3, section 24-31).

The critical property this module provides: the TCP connection is opened
to the *already-validated* IP address (``webhooks.security.resolve_and_validate``),
never re-resolved from the hostname — while TLS SNI, certificate hostname
verification, and the ``Host`` header all still use the *original*
hostname. This is what makes the protection actually effective against DNS
rebinding (section 24): a naive ``requests.post(original_url)`` after
validating a hostname would let the HTTP client resolve DNS a second time,
which could return a different (private) address than the one just
approved.

Uses ``urllib3`` directly rather than the higher-level ``requests`` API:
``urllib3.HTTPConnectionPool``/``HTTPSConnectionPool`` accept ``host`` as
the literal address to connect to plus a separate ``server_hostname`` /
``assert_hostname`` for TLS — exactly the primitive this needs, and one
``requests``'s own ``HTTPAdapter`` does not expose without reaching into
the same urllib3 API underneath it anyway (section 26).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import urllib3
from django.conf import settings

from .errors import (
    WebhookConnectionError,
    WebhookRedirectRejectedError,
    WebhookTimeoutError,
    WebhookTlsError,
    WebhookUnexpectedTransportError,
)

MAX_REDIRECT_STATUS = 399
MIN_REDIRECT_STATUS = 300

#: Only the status code is ever used (section 29 — prefer storing no
#: response body at all); this only bounds how many response bytes this
#: process will read off the socket before giving up on the body, as a
#: defensive cap against a slow/oversized response from a customer-
#: configured endpoint, not a security boundary against SSRF.
MAX_RESPONSE_BYTES_READ = 65536


@dataclass(frozen=True)
class TransportResult:
    status_code: int
    latency_ms: int


class ResponseLike(Protocol):
    status: int

    def read(self, amt: int | None = ..., decode_content: bool | None = ...) -> bytes: ...

    def release_conn(self) -> None: ...


class ConnectionPoolLike(Protocol):
    def request(
        self, method: str, url: str, *, body: bytes, headers: dict[str, str], **kwargs
    ) -> ResponseLike: ...

    def close(self) -> None: ...


class PoolFactory(Protocol):
    def __call__(self, *, scheme: str, ip: str, port: int, hostname: str) -> ConnectionPoolLike: ...


def _build_pool(*, scheme: str, ip: str, port: int, hostname: str) -> urllib3.HTTPConnectionPool:
    timeout = urllib3.Timeout(
        connect=settings.WEBHOOKS_CONNECT_TIMEOUT_SECONDS,
        read=settings.WEBHOOKS_READ_TIMEOUT_SECONDS,
    )
    if scheme == "https":
        return urllib3.HTTPSConnectionPool(
            ip,
            port,
            # The exact DNS-rebinding-safe pinning primitive (section 24):
            # the socket connects to ``ip``; ``server_hostname`` drives TLS
            # SNI and ``assert_hostname`` is what the presented certificate
            # is verified against — both the *original* hostname, never
            # the IP (section 25 — TLS verification is never weakened).
            server_hostname=hostname,
            assert_hostname=hostname,
            cert_reqs="CERT_REQUIRED",
            timeout=timeout,
            retries=False,
            maxsize=1,
        )
    return urllib3.HTTPConnectionPool(ip, port, timeout=timeout, retries=False, maxsize=1)


def send_pinned_request(
    *,
    scheme: str,
    ip: str,
    port: int,
    hostname: str,
    path_and_query: str,
    headers: dict[str, str],
    body: bytes,
    method: str = "POST",
    pool_factory: PoolFactory = _build_pool,
) -> TransportResult:
    """Send exactly one request to ``ip`` (never re-resolving ``hostname``),
    with the original hostname preserved for TLS SNI/certificate
    verification and the ``Host`` header. Redirects are never followed
    (section 27) — a 3xx response is returned to the caller as-is for the
    response classifier to reject.

    ``pool_factory`` is the sole test seam (section 54): tests substitute a
    fake pool to prove *what this function asks urllib3 to do* — which
    host it connects to, which hostname it verifies TLS against — without
    ever performing a real network call.
    """
    request_headers = dict(headers)
    request_headers.setdefault("Host", hostname)
    pool = pool_factory(scheme=scheme, ip=ip, port=port, hostname=hostname)
    start = time.monotonic()
    try:
        response = pool.request(
            method,
            path_and_query,
            body=body,
            headers=request_headers,
            redirect=False,
            preload_content=False,
            assert_same_host=False,
        )
        try:
            # Never stored beyond this call (section 29) — read a bounded
            # amount purely to drain the socket cleanly, then discard it.
            response.read(amt=MAX_RESPONSE_BYTES_READ, decode_content=False)
        finally:
            response.release_conn()
    except urllib3.exceptions.SSLError as exc:
        raise WebhookTlsError() from exc
    except urllib3.exceptions.NewConnectionError as exc:
        # Checked before ``ConnectTimeoutError`` deliberately: urllib3
        # defines ``NewConnectionError`` as a subclass of it, but "connection
        # refused/unreachable" is a distinct, more specific condition than a
        # bare connect timeout — the more specific except clause must come
        # first or it is never reached.
        raise WebhookConnectionError() from exc
    except urllib3.exceptions.ConnectTimeoutError as exc:
        raise WebhookTimeoutError() from exc
    except urllib3.exceptions.ReadTimeoutError as exc:
        raise WebhookTimeoutError() from exc
    except urllib3.exceptions.ProtocolError as exc:
        raise WebhookConnectionError() from exc
    except urllib3.exceptions.HTTPError as exc:
        # Fail-closed classification for anything this module does not
        # explicitly recognize (section 15, 30-31) — never retried
        # automatically, and never logged/persisted beyond this stable code.
        raise WebhookUnexpectedTransportError() from exc
    finally:
        pool.close()
    latency_ms = max(int((time.monotonic() - start) * 1000), 0)

    status_code = response.status
    if MIN_REDIRECT_STATUS <= status_code <= MAX_REDIRECT_STATUS:
        raise WebhookRedirectRejectedError()
    return TransportResult(status_code=status_code, latency_ms=latency_ms)
