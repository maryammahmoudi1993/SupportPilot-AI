"""DNS-rebinding-safety proof for the pinned SMTP transport (Phase 15
checkpoint 2, Part B). ``integrations.security.validate_outbound_host``
alone only protects the moment it runs; these tests prove the actual
connection uses that validated address rather than letting ``smtplib``
re-resolve the hostname a second, unvalidated time — without ever making a
real socket/DNS call."""

from __future__ import annotations

import io

import pytest

from integrations.errors import IntegrationInvalidRequestError
from integrations.providers._smtp_transport import PinnedSMTP, PinnedSmtpEmailBackend


class _FakeSocket:
    """Just enough of the socket API for ``smtplib.SMTP.connect()`` to read
    a 220 greeting and consider the connection established."""

    def __init__(self, greeting: bytes = b"220 fake.smtp.test ESMTP\r\n"):
        self._greeting = greeting
        self.sent: list[bytes] = []

    def makefile(self, mode):
        return io.BytesIO(self._greeting)

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        pass


class TestPinnedSMTPConnectsToTheValidatedAddress:
    def test_socket_connects_to_the_pinned_ip_not_the_hostname(self, monkeypatch):
        captured = {}

        def fake_create_connection(address, timeout, source_address):
            captured["address"] = address
            return _FakeSocket()

        monkeypatch.setattr(
            "integrations.providers._smtp_transport.socket.create_connection",
            fake_create_connection,
        )

        smtp = PinnedSMTP("203.0.113.5", "mail.attacker-controlled.example", 25)

        # The socket connected to the pinned IP — never a fresh resolution
        # of the hostname, which is exactly the DNS-rebinding gap this
        # class exists to close.
        assert captured["address"] == ("203.0.113.5", 25)
        # TLS SNI/certificate-hostname verification (smtplib.starttls uses
        # self._host) still uses the original hostname — pinning the
        # socket must never weaken TLS identity verification.
        assert smtp._host == "mail.attacker-controlled.example"


class TestPinnedSmtpEmailBackendOpen:
    def _backend(self, **kwargs):
        defaults = dict(
            host="mail.example.test",
            port=587,
            username=None,
            password=None,
            use_tls=True,
            fail_silently=False,
        )
        defaults.update(kwargs)
        return PinnedSmtpEmailBackend(**defaults)

    def test_open_rejects_a_destination_that_resolves_to_a_private_address(self, monkeypatch):
        monkeypatch.setattr(
            "integrations.providers._smtp_transport.validate_outbound_host",
            lambda host, port: (_ for _ in ()).throw(
                IntegrationInvalidRequestError("This destination is not allowed.")
            ),
        )

        def _fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
            raise AssertionError("PinnedSMTP must never be constructed for a blocked destination")

        monkeypatch.setattr("integrations.providers._smtp_transport.PinnedSMTP", _fail_if_called)

        backend = self._backend()
        with pytest.raises(IntegrationInvalidRequestError):
            backend.open()

    def test_open_connects_using_the_exact_ip_validation_approved(self, monkeypatch):
        """The address ``validate_outbound_host`` approves is the exact
        address the connection is built with — no second, independent
        resolution happens in between (the DNS-rebinding closure)."""
        monkeypatch.setattr(
            "integrations.providers._smtp_transport.validate_outbound_host",
            lambda host, port: "198.51.100.7",
        )

        captured = {}

        class _FakeConnection:
            def __init__(self, pinned_ip, host, port, **kwargs):
                captured["pinned_ip"] = pinned_ip
                captured["host"] = host
                captured["port"] = port

            def starttls(self, context=None):
                captured["starttls"] = True

            def login(self, username, password):  # pragma: no cover - not exercised here
                captured["login"] = (username, password)

        monkeypatch.setattr("integrations.providers._smtp_transport.PinnedSMTP", _FakeConnection)

        backend = self._backend()
        result = backend.open()

        assert result is True
        assert captured["pinned_ip"] == "198.51.100.7"
        assert captured["host"] == "mail.example.test"
        assert captured["port"] == 587
        assert captured["starttls"] is True

    def test_use_ssl_falls_back_to_the_unpinned_base_implementation(self, monkeypatch):
        """``use_ssl`` is not exposed by this provider's credentials schema
        today; the backend must not silently mis-pin a mode it never
        actually validates against, so it defers to Django's own
        implementation for that mode rather than pretending to pin it."""
        called = {}

        def fake_super_open(self):
            called["base_open"] = True
            return True

        monkeypatch.setattr(
            "integrations.providers._smtp_transport.validate_outbound_host",
            lambda host, port: (_ for _ in ()).throw(
                AssertionError("use_ssl must not call validate_outbound_host via this path")
            ),
        )
        monkeypatch.setattr(
            "django.core.mail.backends.smtp.EmailBackend.open", fake_super_open, raising=True
        )

        backend = self._backend(use_ssl=True, use_tls=False)
        result = backend.open()

        assert result is True
        assert called.get("base_open") is True
