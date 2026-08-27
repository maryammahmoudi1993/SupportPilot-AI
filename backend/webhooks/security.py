"""SSRF-safe destination validation (Phase 10 Block 3, section 19-24, 50-53).

Every outbound webhook attempt calls ``resolve_and_validate`` immediately
before that attempt — never a value cached from endpoint creation time
(section 23). ``ipaddress`` classification is used instead of a hand-rolled
CIDR list (section 21) so IPv4-private/loopback/link-local/multicast/
reserved *and* their IPv6 equivalents are all covered by the standard
library's own, actively-maintained classification.

This module never performs network I/O itself — see ``webhooks/transport.py``
for the pinned connection that actually uses the address this module
approves.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

from .errors import (
    WebhookDestinationBlockedError,
    WebhookDnsResolutionError,
    WebhookInvalidURLError,
)

#: Explicitly called out by name (section 21) even though ``is_private``
#: already covers the 169.254.0.0/16 link-local block it lives in — this
#: makes the cloud-metadata rejection self-evident in the code, not just an
#: incidental side effect of the broader link-local check.
CLOUD_METADATA_ADDRESS = ipaddress.ip_address("169.254.169.254")


@dataclass(frozen=True)
class ParsedWebhookURL:
    scheme: str
    hostname: str
    port: int
    path_and_query: str


def _allowed_schemes() -> frozenset[str]:
    if settings.WEBHOOKS_ALLOW_INSECURE_HTTP:
        return frozenset({"http", "https"})
    return frozenset({"https"})


def parse_webhook_url(url: str) -> ParsedWebhookURL:
    """Strict, minimal URL parsing (section 20). Rejects anything this
    module cannot fully reason about rather than silently reinterpreting
    it — a malformed URL is never "fixed up"."""
    if not url or len(url) > settings.WEBHOOKS_MAX_URL_LENGTH:
        raise WebhookInvalidURLError()
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise WebhookInvalidURLError() from exc

    if parts.scheme not in _allowed_schemes():
        raise WebhookInvalidURLError()
    if parts.fragment:
        raise WebhookInvalidURLError()
    if parts.username or parts.password:
        raise WebhookInvalidURLError()
    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError as exc:
        # ``urlsplit`` defers port/hostname parsing errors (malformed port,
        # invalid bracketed IPv6 literal) to attribute access.
        raise WebhookInvalidURLError() from exc
    if not hostname:
        raise WebhookInvalidURLError()

    default_port = 443 if parts.scheme == "https" else 80
    port = port if port is not None else default_port
    if not (0 < port <= 65535):
        raise WebhookInvalidURLError()

    path_and_query = parts.path or "/"
    if parts.query:
        path_and_query = f"{path_and_query}?{parts.query}"

    return ParsedWebhookURL(
        scheme=parts.scheme, hostname=hostname.lower(), port=port, path_and_query=path_and_query
    )


def is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Standard-library classification (section 21) — deliberately not a
    hand-maintained CIDR list. Covers loopback, private, link-local
    (including the 169.254.169.254 cloud metadata address), multicast,
    unspecified, and reserved ranges for both IPv4 and IPv6, plus an
    IPv4-mapped IPv6 address unwrapped to its embedded IPv4 form (section 21,
    ``::ffff:169.254.169.254``-style bypass attempts)."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return is_blocked_address(address.ipv4_mapped)
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or address == CLOUD_METADATA_ADDRESS
    )


def resolve_and_validate(hostname: str, port: int) -> str:
    """Resolve every address for ``hostname`` and fail closed unless *all*
    of them are safe (section 21, 24, 52) — never "pick the public one and
    ignore the private one". Returns one approved, connectable IP address
    string (the first result in resolver order — a deterministic choice
    when multiple safe addresses exist, section 24).

    Callers must pass the returned address straight into the pinned
    transport (``webhooks.transport``) without re-resolving — see that
    module's docstring for why a second resolution would defeat this
    entirely (section 24, DNS rebinding).
    """
    normalized = hostname.strip().lower()
    if normalized in ("localhost", "localhost."):
        # Explicit literal check (section 22) — belt-and-braces on top of
        # the resolved-address check below, which independently also
        # rejects whatever "localhost" actually resolves to.
        raise WebhookDestinationBlockedError()

    try:
        # ``socket.getaddrinfo`` on a literal IP address returns it
        # directly without a network DNS round-trip; only an actual
        # hostname triggers a real resolver query. This is the single DNS
        # resolution point for a given attempt (section 23-24).
        results = socket.getaddrinfo(normalized, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebhookDnsResolutionError() from exc
    if not results:
        raise WebhookDnsResolutionError()

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _type, _proto, _canon, sockaddr in results:
        raw = str(sockaddr[0])
        if family == socket.AF_INET6:
            raw = raw.split("%", 1)[0]  # strip a zone/scope id, e.g. "fe80::1%eth0"
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError as exc:  # pragma: no cover - defensive, OS always returns valid literals
            raise WebhookDnsResolutionError() from exc

    if any(is_blocked_address(address) for address in addresses):
        raise WebhookDestinationBlockedError()

    return str(addresses[0])
