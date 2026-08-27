"""URL parsing + SSRF destination validation (Phase 10 Block 3, section
20-24, 50-53). No test here ever performs a real network connection —
``resolve_and_validate`` only resolves DNS (or classifies a literal IP
directly); nothing here calls the transport."""

from __future__ import annotations

import ipaddress
import socket

import pytest

from webhooks.errors import (
    WebhookDestinationBlockedError,
    WebhookDnsResolutionError,
    WebhookInvalidURLError,
)
from webhooks.security import is_blocked_address, parse_webhook_url, resolve_and_validate

# ---------------------------------------------------------------------------
# URL parsing (section 20)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "ftp://example.com/",
        "file:///etc/passwd",
        "https://",
        "https:///path",
        "https://user@example.com/",
        "https://user:pass@example.com/",
        "https://example.com/#fragment",
        "https://example.com:99999/",
        "https://example.com:-1/",
        "",
        "https://" + "a" * 3000 + ".com/",
    ],
)
def test_parse_webhook_url_rejects_malformed_urls(url):
    with pytest.raises(WebhookInvalidURLError):
        parse_webhook_url(url)


def test_parse_webhook_url_rejects_http_by_default(settings):
    settings.WEBHOOKS_ALLOW_INSECURE_HTTP = False
    with pytest.raises(WebhookInvalidURLError):
        parse_webhook_url("http://example.com/hook")


def test_parse_webhook_url_allows_http_when_server_opted_in(settings):
    settings.WEBHOOKS_ALLOW_INSECURE_HTTP = True
    parsed = parse_webhook_url("http://example.com/hook")
    assert parsed.scheme == "http"
    assert parsed.port == 80


def test_parse_webhook_url_normalizes_valid_https_url():
    parsed = parse_webhook_url("https://Example.com:8443/a/b?x=1")
    assert parsed.scheme == "https"
    assert parsed.hostname == "example.com"
    assert parsed.port == 8443
    assert parsed.path_and_query == "/a/b?x=1"


def test_parse_webhook_url_defaults_path_to_root():
    parsed = parse_webhook_url("https://example.com")
    assert parsed.path_and_query == "/"


# ---------------------------------------------------------------------------
# IP classification (section 21)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "0.0.0.0",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "169.254.1.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::",
        "::ffff:169.254.169.254",  # IPv4-mapped IPv6 bypass attempt
    ],
)
def test_is_blocked_address_rejects_internal_ranges(address):
    assert is_blocked_address(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2001:4860:4860::8888"])
def test_is_blocked_address_allows_public_ranges(address):
    assert is_blocked_address(ipaddress.ip_address(address)) is False


# ---------------------------------------------------------------------------
# SSRF test matrix (section 50) — required cases against the real resolver.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://localhost/",
        "https://LOCALHOST/",
        "https://0.0.0.0/",
        "https://10.0.0.1/",
        "https://172.16.0.1/",
        "https://192.168.1.1/",
        "https://169.254.169.254/",
        "https://[fe80::1]/",
        "https://[fc00::1]/",
        "https://[ff02::1]/",
        "https://[::]/",
    ],
)
def test_ssrf_matrix_blocked_before_reaching_the_transport(url):
    """Every case here must be rejected purely by parsing/DNS validation —
    none of them ever reach ``webhooks.transport`` (proven end-to-end,
    with a transport call-counting fake, in
    ``test_services.py::test_ssrf_blocked_destination_never_calls_transport``)."""
    with pytest.raises((WebhookInvalidURLError, WebhookDestinationBlockedError)):
        parsed = parse_webhook_url(url)
        resolve_and_validate(parsed.hostname, parsed.port)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "https://user:pass@example.com/",
        "https://example.com/#frag",
        "https://example.com:99999/",
    ],
)
def test_ssrf_matrix_url_rejected_before_any_resolution(url, monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("DNS must never be resolved for a structurally-rejected URL")

    monkeypatch.setattr("socket.getaddrinfo", _fail_if_called)
    with pytest.raises(WebhookInvalidURLError):
        parse_webhook_url(url)


# ---------------------------------------------------------------------------
# DNS -> private / multiple-result / fail-closed (section 51-53)
# ---------------------------------------------------------------------------


def _fake_getaddrinfo(*addresses):
    def _resolver(host, port, proto=None, **kwargs):
        return [
            (
                socket.AF_INET6 if ":" in addr else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (addr, port),
            )
            for addr in addresses
        ]

    return _resolver


def test_dns_resolves_to_private_address_is_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("192.168.1.10"))
    with pytest.raises(WebhookDestinationBlockedError):
        resolve_and_validate("webhook.example", 443)


def test_multiple_dns_results_one_private_fails_closed(monkeypatch):
    """Section 52: a public address AND a private address must both be
    rejected together — never silently pick the public one."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34", "192.168.1.10"))
    with pytest.raises(WebhookDestinationBlockedError):
        resolve_and_validate("webhook.example", 443)


def test_dns_changes_between_attempts_second_attempt_blocked(monkeypatch):
    """Section 53: validation is per-attempt, not cached from a prior
    successful attempt."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    ip = resolve_and_validate("webhook.example", 443)
    assert ip == "93.184.216.34"

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("192.168.1.10"))
    with pytest.raises(WebhookDestinationBlockedError):
        resolve_and_validate("webhook.example", 443)


def test_dns_resolution_failure_is_retryable_error():
    def _raise(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    import socket as socket_module

    original = socket_module.getaddrinfo
    socket_module.getaddrinfo = _raise
    try:
        with pytest.raises(WebhookDnsResolutionError) as exc_info:
            resolve_and_validate("nonexistent.invalid", 443)
        assert exc_info.value.retryable is True
    finally:
        socket_module.getaddrinfo = original


def test_multiple_safe_addresses_deterministic_choice(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34", "8.8.8.8"))
    assert resolve_and_validate("webhook.example", 443) == "93.184.216.34"


def test_empty_resolver_result_is_a_dns_resolution_error(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(WebhookDnsResolutionError):
        resolve_and_validate("webhook.example", 443)


def test_zero_port_is_rejected():
    with pytest.raises(WebhookInvalidURLError):
        parse_webhook_url("https://example.com:0/")
