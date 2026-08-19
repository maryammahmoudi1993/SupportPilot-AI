"""SMTP notification adapter SDK-boundary tests (section 59, 100)."""

from __future__ import annotations

import smtplib

import pytest

from integrations.errors import (
    IntegrationAuthenticationFailedError,
    IntegrationInvalidRequestError,
    IntegrationTemporarilyUnavailableError,
    IntegrationTimeoutError,
)
from integrations.providers.email_provider import SmtpNotificationProvider

CREDENTIALS = {"host": "smtp.example.com", "port": 587, "username": "user", "password": "pw"}


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
