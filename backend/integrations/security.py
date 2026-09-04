"""SSRF-safe destination validation for provider adapters that open a raw
outbound network connection to a workspace-supplied host/port rather than an
HTTP(S) URL (Phase 15 finding: the SMTP notification provider took
``credentials["host"]``/``credentials["port"]`` directly from workspace
configuration with no destination check, unlike the Phase 10 webhook
delivery path).

Reuses the same fail-closed global-routability classification as
``webhooks.security.is_blocked_address`` (a pure function with no
webhooks-specific behavior) so the two modules never drift on what counts as
a safe destination. This module performs its own DNS resolution rather than
importing ``webhooks.security.resolve_and_validate`` directly, since that
helper raises webhook-specific error types.

Only owner/admin workspace members can configure integration credentials
(``integrations.permissions.CanManageIntegrations``), so this is
defense-in-depth against a compromised or malicious admin using a
provider-credential field to probe or reach internal/private network
services from the application server, not a public-input SSRF path.

``validate_outbound_host`` returns the single approved, connectable IP
address it resolved — mirroring ``webhooks.security.resolve_and_validate``'s
contract exactly, and for the same reason (section 24 of the Phase 15
brief, DNS rebinding): a caller that validates a hostname and then lets its
network client re-resolve that same hostname to actually connect has not
closed the SSRF gap at all, only delayed the check by one resolution. See
``integrations.providers._smtp_transport`` for the pinned SMTP connection
that actually uses this returned address instead of re-resolving.
"""

from __future__ import annotations

import ipaddress
import socket

from webhooks.security import is_blocked_address

from .errors import IntegrationInvalidRequestError


def validate_outbound_host(hostname: str | None, port: int) -> str:
    """Resolve ``hostname`` and fail closed unless every resolved address is
    a verified, globally-routable Internet address. Raises
    ``IntegrationInvalidRequestError`` (never a raw socket/DNS exception) on
    any rejection — a missing host, an unresolvable host, or a host that
    resolves to a private/loopback/link-local/metadata/multicast address.

    Returns one approved IP address string (the first result in resolver
    order) for callers that can pin their actual connection to it; callers
    that only want the fail-closed check (and will let their own network
    client resolve the hostname again) may simply discard the return value
    — but see the DNS-rebinding note above for why that is not itself a
    complete guarantee against a hostname that resolves differently a
    moment later.
    """
    if not hostname or not hostname.strip():
        raise IntegrationInvalidRequestError("No destination host is configured.")

    normalized = hostname.strip().lower()
    if normalized in ("localhost", "localhost."):
        raise IntegrationInvalidRequestError("This destination is not allowed.")

    try:
        results = socket.getaddrinfo(normalized, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise IntegrationInvalidRequestError("This destination could not be resolved.") from exc
    if not results:
        raise IntegrationInvalidRequestError("This destination could not be resolved.")

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _type, _proto, _canon, sockaddr in results:
        raw = str(sockaddr[0])
        if family == socket.AF_INET6:
            raw = raw.split("%", 1)[0]
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError as exc:  # pragma: no cover - defensive, OS always returns valid literals
            raise IntegrationInvalidRequestError("This destination could not be resolved.") from exc

    if any(is_blocked_address(address) for address in addresses):
        raise IntegrationInvalidRequestError("This destination is not allowed.")

    return str(addresses[0])
