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
"""

from __future__ import annotations

import ipaddress
import socket

from webhooks.security import is_blocked_address

from .errors import IntegrationInvalidRequestError


def validate_outbound_host(hostname: str | None, port: int) -> None:
    """Resolve ``hostname`` and fail closed unless every resolved address is
    a verified, globally-routable Internet address. Raises
    ``IntegrationInvalidRequestError`` (never a raw socket/DNS exception) on
    any rejection — a missing host, an unresolvable host, or a host that
    resolves to a private/loopback/link-local/metadata/multicast address.
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
