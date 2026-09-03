"""DNS-rebinding-safe SMTP transport (Phase 15 checkpoint 2, Part B).

``integrations.security.validate_outbound_host`` alone only protects against
SSRF up to the moment it runs: ``django.core.mail.backends.smtp.EmailBackend``
constructs a plain ``smtplib.SMTP(host, port)``, and ``smtplib`` performs its
*own*, entirely independent ``socket.create_connection`` (hence its own DNS
resolution) when it actually opens the socket. Nothing carries the first
resolution's approved address into that second one — a hostname an attacker
controls could resolve to a public address for the validation call and to a
private/internal address moments later for the real connect, defeating the
check entirely (the same class of gap ``webhooks/transport.py`` already
closes for outbound HTTP webhook delivery).

The fix mirrors ``webhooks/transport.py``'s approach for HTTP: connect to the
already-validated literal IP address directly, while everything that needs
the original hostname (TLS SNI plus certificate hostname verification via
``starttls(server_hostname=...)``) keeps using it. This overrides only the
one method (``_get_socket``) responsible for turning ``(host, port)`` into a
live socket — not a reimplementation of SMTP itself, which is exactly what
keeps this a narrow, stdlib-based fix rather than a custom networking stack.

Only STARTTLS-over-plain-connection (``smtplib.SMTP``) is pinned here — the
only mode this provider's credentials schema exposes (``use_tls``). A future
``use_ssl``/implicit-TLS (``smtplib.SMTP_SSL``) credential would need the
analogous ``_get_socket`` override on that class before being trusted the
same way.
"""

from __future__ import annotations

import smtplib
import socket

from django.core.mail.backends.smtp import EmailBackend as DjangoSmtpEmailBackend
from django.core.mail.utils import DNS_NAME

from ..security import validate_outbound_host


class PinnedSMTP(smtplib.SMTP):
    """``smtplib.SMTP`` that connects to a pre-validated IP address instead
    of re-resolving ``host`` itself. ``self._host`` (used by
    ``smtplib.SMTP.starttls`` as the TLS ``server_hostname``) is left as the
    original hostname passed to ``__init__`` — only the *socket* connects to
    the pinned address, so certificate hostname verification is never
    weakened (mirrors ``webhooks/transport.py``'s ``server_hostname``/
    ``assert_hostname`` split for the same reason)."""

    def __init__(self, pinned_ip: str, host: str = "", port: int = 0, **kwargs) -> None:
        self._pinned_ip = pinned_ip
        super().__init__(host, port, **kwargs)

    def _get_socket(self, host, port, timeout):
        # The one line this class exists to change: connect to the
        # validated literal address, never to ``host`` (which would trigger
        # a second, unvalidated DNS resolution). ``socket.create_connection``
        # on a literal IP never performs a network DNS query.
        if timeout is not None and not timeout:
            raise ValueError("Non-blocking socket (timeout=0) is not supported")
        return socket.create_connection((self._pinned_ip, port), timeout, self.source_address)


class PinnedSmtpEmailBackend(DjangoSmtpEmailBackend):
    """Django SMTP backend whose ``open()`` validates the destination via
    ``integrations.security.validate_outbound_host`` and then connects to
    the *exact* IP address that call approved — never letting ``smtplib``
    re-resolve ``self.host`` on its own (the DNS-rebinding gap this module
    exists to close). Structurally a copy of
    ``django.core.mail.backends.smtp.EmailBackend.open`` with exactly one
    behavioral change: which class builds the connection and what it's
    given to connect to.

    Only STARTTLS mode is pinned; ``use_ssl`` (implicit TLS, ``SMTP_SSL``)
    falls back to the unpinned base implementation rather than silently
    mis-pinning a mode this provider's credentials schema does not
    currently expose to callers (see the module docstring)."""

    def open(self):
        if self.connection:
            return False
        if self._partial_connection is not None:
            self._close_connection(self._partial_connection)
            self._partial_connection = None

        if self.use_ssl:
            return super().open()

        pinned_ip = validate_outbound_host(self.host, self.port)

        connection_params = {"local_hostname": DNS_NAME.get_fqdn()}
        if self.timeout is not None:
            connection_params["timeout"] = self.timeout
        try:
            self._partial_connection = PinnedSMTP(
                pinned_ip, self.host, self.port, **connection_params
            )
            if self.use_tls:
                self._partial_connection.starttls(context=self.ssl_context)
            if self.username and self.password:
                self._partial_connection.login(self.username, self.password)
            self.connection = self._partial_connection
            self._partial_connection = None
            return True
        except OSError:
            if not self.fail_silently:
                raise
