"""SSRF-safe destination validation (Phase 10 Block 3, section 19-24, 50-53;
Block 3 remediation section 2: global-routability fail-closed gate).

Every outbound webhook attempt calls ``resolve_and_validate`` immediately
before that attempt — never a value cached from endpoint creation time
(section 23).

Destination classification is a fail-closed **allowlist**, not a blacklist:
an address is only usable if ``ip.is_global`` — every non-routable
special-purpose range (loopback, private, link-local, cloud metadata,
unspecified, reserved, *and* less commonly enumerated ranges like the
100.64.0.0/10 carrier-grade-NAT shared space, the 198.18.0.0/15
benchmarking range, and the 192.0.2.0/24 / 198.51.100.0/24 / 203.0.113.0/24
documentation ranges) is excluded by this one check, rather than requiring
each to be hand-enumerated as a growing blacklist that a Python version
difference — or simply an incomplete list — could silently miss.

``is_global`` alone is not quite sufficient, though: verified directly
against this project's Python/stdlib version (see the module test suite),
CPython's ``ipaddress`` reports ``is_global=True`` for two categories that
must never be treated as valid webhook destinations:

* **all multicast addresses** (IPv4 224.0.0.0/4 and IPv6 ff00::/8) — not a
  meaningful unicast TCP destination and explicitly excluded;
* **deprecated IPv6 site-local addresses** (fec0::/10, RFC 3879) — excluded
  explicitly since ``is_global`` does not classify them as non-global.

Both are checked explicitly in addition to ``is_global`` below — not as a
second blacklist layered under the allowlist, but as documented, verified
corrections to what the allowlist alone would otherwise accept.

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

#: Deprecated IPv6 site-local addresses (RFC 3879) — CPython's
#: ``ipaddress.IPv6Address.is_global`` reports ``True`` for this range
#: (verified directly, see ``test_security.py``), so it is excluded here
#: explicitly rather than trusted to the allowlist check.
_DEPRECATED_SITE_LOCAL_IPV6 = ipaddress.ip_network("fec0::/10")


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
    """Fail-closed global-routability gate (section 2 of the Block 3
    remediation): an address is usable as a webhook destination only if it
    is a verified, globally-routable Internet address — every other
    special-purpose range (loopback, private, link-local including the
    169.254.169.254 cloud-metadata address, unspecified, reserved,
    carrier-grade NAT, benchmarking, documentation/TEST-NET, ...) is
    rejected by the single ``not address.is_global`` check below, not by
    enumerating each one.

    An IPv4-mapped IPv6 address is unwrapped to its embedded IPv4 form
    first (``::ffff:169.254.169.254``/``::ffff:100.64.0.1``-style bypass
    attempts) — ``is_global`` on the *wrapped* IPv6 form does not reliably
    reflect the embedded address's own routability.

    Multicast and deprecated IPv6 site-local addresses are excluded
    explicitly on top of ``is_global`` — verified corrections to a real
    stdlib classification gap, not a parallel blacklist (see the module
    docstring).
    """
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return is_blocked_address(address.ipv4_mapped)
    if address.is_multicast:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address in _DEPRECATED_SITE_LOCAL_IPV6:
        return True
    return not address.is_global


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
