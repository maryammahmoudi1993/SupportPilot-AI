"""SMTP notification adapter SDK-boundary tests (section 59, 100)."""

from __future__ import annotations

import smtplib
import socket

import pytest

from integrations.errors import (
    IntegrationAuthenticationFailedError,
    IntegrationInvalidRequestError,
    IntegrationTemporarilyUnavailableError,
    IntegrationTimeoutError,
)
from integrations.providers.email_provider import SmtpNotificationProvider

CREDENTIALS = {"host": "smtp.example.com", "port": 587, "username": "user", "password": "pw"}


def _fake_getaddrinfo_for(*ips: str):
    """Deterministic ``socket.getaddrinfo`` fake — normal tests never
    perform real DNS resolution (section 64)."""

    def _fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    return _fake


@pytest.fixture(autouse=True)
def _resolve_smtp_host_to_public_ip(monkeypatch):
    """By default every test resolves ``smtp.example.com`` to a public IP,
    so existing SDK-boundary tests are unaffected by the SSRF destination
    check added in Phase 15; individual tests override this to exercise the
    check itself."""
    monkeypatch.setattr(
        "integrations.security.socket.getaddrinfo", _fake_getaddrinfo_for("8.8.8.8")
    )


class _FakeConnection:
    def __init__(self, *, open_error: Exception | None = None, send_error: Exception | None = None):
        self.open_error = open_error
        self.send_error = send_error
        self.opened = False
        self.closed = False

    def open(self):
        if self.open_error is not None:
            raise self.open_error
        self.opened = True

    def close(self):
        self.closed = True


def _patch_connection(monkeypatch, connection) -> None:
    monkeypatch.setattr(
        "integrations.providers.email_provider.get_connection", lambda **kwargs: connection
    )


@pytest.fixture
def provider() -> SmtpNotificationProvider:
    return SmtpNotificationProvider()


class TestSend:
    def test_success(self, monkeypatch, provider):
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        monkeypatch.setattr(
            "integrations.providers.email_provider.EmailMessage.send", lambda self, **kw: 1
        )
        result = provider.send(
            credentials=CREDENTIALS,
            configuration={"from_email": "support@example.com"},
            recipient_email="a@example.com",
            subject="Hi",
            body="Body",
            idempotency_key="k1",
            timeout_seconds=5,
        )
        assert result.status == "sent"
        assert connection.opened is True
        assert connection.closed is True

    def test_missing_from_email_rejected(self, monkeypatch, provider):
        _patch_connection(monkeypatch, _FakeConnection())
        with pytest.raises(IntegrationInvalidRequestError):
            provider.send(
                credentials={"host": "smtp.example.com"},
                configuration={},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )

    def test_auth_failure(self, monkeypatch, provider):
        connection = _FakeConnection(open_error=smtplib.SMTPAuthenticationError(535, b"bad creds"))
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationAuthenticationFailedError):
            provider.send(
                credentials=CREDENTIALS,
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )
        assert connection.closed is True

    def test_recipient_refused(self, monkeypatch, provider):
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        monkeypatch.setattr(
            "integrations.providers.email_provider.EmailMessage.send",
            lambda self, **kw: (_ for _ in ()).throw(
                smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no such user")})
            ),
        )
        with pytest.raises(IntegrationInvalidRequestError):
            provider.send(
                credentials=CREDENTIALS,
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )

    def test_timeout(self, monkeypatch, provider):
        connection = _FakeConnection(open_error=TimeoutError())
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationTimeoutError):
            provider.send(
                credentials=CREDENTIALS,
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )

    def test_generic_smtp_failure_is_temporarily_unavailable(self, monkeypatch, provider):
        connection = _FakeConnection(open_error=smtplib.SMTPException("boom"))
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationTemporarilyUnavailableError):
            provider.send(
                credentials=CREDENTIALS,
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )


class TestSsrfDestinationValidation:
    """Phase 15 finding: the SMTP provider took ``host``/``port`` directly
    from workspace-supplied credentials with no destination validation,
    unlike the Phase 10 webhook delivery path. These prove the fix without
    ever making a real DNS/socket call (section 23, 64)."""

    def test_send_rejects_private_ip_destination(self, monkeypatch, provider):
        monkeypatch.setattr(
            "integrations.security.socket.getaddrinfo", _fake_getaddrinfo_for("10.0.0.5")
        )
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationInvalidRequestError):
            provider.send(
                credentials={**CREDENTIALS, "host": "internal-smtp.attacker.example"},
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )
        # The blocked destination must never be connected to.
        assert connection.opened is False

    def test_send_rejects_loopback_and_metadata_destination(self, monkeypatch, provider):
        for ip in ("127.0.0.1", "169.254.169.254", "::1"):
            monkeypatch.setattr(
                "integrations.security.socket.getaddrinfo", _fake_getaddrinfo_for(ip)
            )
            connection = _FakeConnection()
            _patch_connection(monkeypatch, connection)
            with pytest.raises(IntegrationInvalidRequestError):
                provider.send(
                    credentials={**CREDENTIALS, "host": "attacker-controlled.example"},
                    configuration={"from_email": "support@example.com"},
                    recipient_email="a@example.com",
                    subject="Hi",
                    body="Body",
                    idempotency_key="k1",
                    timeout_seconds=5,
                )
            assert connection.opened is False

    def test_send_rejects_literal_localhost_without_resolving(self, monkeypatch, provider):
        def _fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
            raise AssertionError("literal localhost must be rejected before DNS resolution")

        monkeypatch.setattr("integrations.security.socket.getaddrinfo", _fail_if_called)
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationInvalidRequestError):
            provider.send(
                credentials={**CREDENTIALS, "host": "localhost"},
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )
        assert connection.opened is False

    def test_send_rejects_when_any_resolved_address_is_private(self, monkeypatch, provider):
        # A hostname resolving to a mix of public and private addresses must
        # fail closed on the private one, never "pick the public one".
        monkeypatch.setattr(
            "integrations.security.socket.getaddrinfo",
            _fake_getaddrinfo_for("8.8.8.8", "10.0.0.5"),
        )
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationInvalidRequestError):
            provider.send(
                credentials={**CREDENTIALS, "host": "mixed.example"},
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )
        assert connection.opened is False

    def test_probe_rejects_private_ip_destination(self, monkeypatch, provider):
        monkeypatch.setattr(
            "integrations.security.socket.getaddrinfo", _fake_getaddrinfo_for("192.168.1.1")
        )
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationInvalidRequestError):
            provider.probe(
                credentials={**CREDENTIALS, "host": "internal.example"}, timeout_seconds=5
            )
        assert connection.opened is False

    def test_send_rejects_missing_host(self, monkeypatch, provider):
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationInvalidRequestError):
            provider.send(
                credentials={**CREDENTIALS, "host": ""},
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )
        assert connection.opened is False

    def test_send_allows_public_destination(self, monkeypatch, provider):
        # Default fixture already resolves CREDENTIALS["host"] to 8.8.8.8.
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        monkeypatch.setattr(
            "integrations.providers.email_provider.EmailMessage.send", lambda self, **kw: 1
        )
        result = provider.send(
            credentials=CREDENTIALS,
            configuration={"from_email": "support@example.com"},
            recipient_email="a@example.com",
            subject="Hi",
            body="Body",
            idempotency_key="k1",
            timeout_seconds=5,
        )
        assert result.status == "sent"
        assert connection.opened is True


class TestHeaderInjection:
    """Phase 15 checkpoint 3, Part E: ``subject``/``body`` come directly
    from LLM tool-call arguments (untrusted, prompt-injectable text) and
    ``recipient_email`` from a Customer record. These prove the actual
    protection (Django refuses to construct a message containing a raw
    CRLF in a header) and that the provider never lets that refusal
    surface as an unclassified exception."""

    def test_django_email_message_rejects_crlf_in_subject(self):
        from django.core.mail import BadHeaderError, EmailMessage

        message = EmailMessage(
            subject="Hi\r\nX-Injected: evil",
            body="b",
            from_email="a@example.com",
            to=["victim@example.com"],
        )
        with pytest.raises(BadHeaderError):
            message.message()

    def test_django_email_message_rejects_crlf_in_recipient(self):
        """A recipient value containing a CRLF (an attempted
        ``victim@example.com\\r\\nBcc: attacker@example.com`` expansion)
        is refused the same way — no additional recipient is ever
        injectable via the address field."""
        from django.core.mail import BadHeaderError, EmailMessage

        message = EmailMessage(
            subject="Hi",
            body="b",
            from_email="a@example.com",
            to=["victim@example.com\r\nBcc: attacker@example.com"],
        )
        with pytest.raises(BadHeaderError):
            message.message()

    def test_send_never_leaks_the_raw_bad_header_exception(self, monkeypatch, provider):
        from django.core.mail import BadHeaderError

        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        monkeypatch.setattr(
            "integrations.providers.email_provider.EmailMessage.send",
            lambda self, **kw: (_ for _ in ()).throw(
                BadHeaderError("Header values can't contain newlines")
            ),
        )
        with pytest.raises(IntegrationInvalidRequestError):
            provider.send(
                credentials=CREDENTIALS,
                configuration={"from_email": "support@example.com"},
                recipient_email="a@example.com",
                subject="Hi\r\nX-Injected: evil",
                body="Body",
                idempotency_key="k1",
                timeout_seconds=5,
            )
        # The connection is still cleanly closed, no side effect leaked.
        assert connection.closed is True


class TestProbe:
    def test_probe_opens_and_closes_without_sending(self, monkeypatch, provider):
        connection = _FakeConnection()
        _patch_connection(monkeypatch, connection)
        provider.probe(credentials=CREDENTIALS, timeout_seconds=5)
        assert connection.opened is True
        assert connection.closed is True

    def test_probe_auth_failure(self, monkeypatch, provider):
        connection = _FakeConnection(open_error=smtplib.SMTPAuthenticationError(535, b"bad"))
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationAuthenticationFailedError):
            provider.probe(credentials=CREDENTIALS, timeout_seconds=5)

    def test_probe_timeout(self, monkeypatch, provider):
        connection = _FakeConnection(open_error=TimeoutError())
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationTimeoutError):
            provider.probe(credentials=CREDENTIALS, timeout_seconds=5)

    def test_probe_generic_failure_is_temporarily_unavailable(self, monkeypatch, provider):
        connection = _FakeConnection(open_error=smtplib.SMTPException("boom"))
        _patch_connection(monkeypatch, connection)
        with pytest.raises(IntegrationTemporarilyUnavailableError):
            provider.probe(credentials=CREDENTIALS, timeout_seconds=5)
