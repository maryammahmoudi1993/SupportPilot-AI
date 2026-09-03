"""SMTP-backed ``NotificationProvider`` adapter (section 59).

Deliberately lightweight: Django's own ``django.core.mail`` SMTP backend
rather than a large vendor email SDK, since the project has no existing
email-vendor dependency to justify one (section 59, 133-134 analog for
email). Credentials come from the owning ``IntegrationConnection`` only —
never from a tool argument.

Destination validation is layered (Phase 15 checkpoint 2): the explicit
``validate_outbound_host`` call below is a fast, easily-tested advisory
check that rejects an obviously-blocked destination before even
constructing a connection; the actual connection is built by
``PinnedSmtpEmailBackend`` (``_smtp_transport``), which is the authoritative
layer — it re-validates and pins the real socket to that validated address,
closing the DNS-rebinding gap a check-then-reconnect sequence would
otherwise leave open (see that module's docstring).
"""

from __future__ import annotations

import smtplib
from email.utils import make_msgid

from django.core.mail import EmailMessage, get_connection

from ..errors import (
    IntegrationAuthenticationFailedError,
    IntegrationInvalidRequestError,
    IntegrationTemporarilyUnavailableError,
    IntegrationTimeoutError,
)
from ..security import validate_outbound_host
from .base import NormalizedNotification

_PINNED_SMTP_BACKEND = "integrations.providers._smtp_transport.PinnedSmtpEmailBackend"


class SmtpNotificationProvider:
    """Typed ``NotificationProvider`` backed by SMTP."""

    name = "smtp"

    def probe(self, *, credentials: dict, timeout_seconds: float) -> None:
        """Read-only connection-test probe: opens and closes the SMTP
        connection without sending anything."""
        host = credentials.get("host")
        port = int(credentials.get("port", 587))
        validate_outbound_host(host, port)

        connection = get_connection(
            backend=_PINNED_SMTP_BACKEND,
            host=host,
            port=port,
            username=credentials.get("username"),
            password=credentials.get("password"),
            use_tls=bool(credentials.get("use_tls", True)),
            timeout=timeout_seconds,
        )
        try:
            connection.open()
        except smtplib.SMTPAuthenticationError as exc:
            raise IntegrationAuthenticationFailedError() from exc
        except TimeoutError as exc:
            raise IntegrationTimeoutError() from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise IntegrationTemporarilyUnavailableError() from exc
        finally:
            connection.close()

    def send(
        self,
        *,
        credentials: dict,
        configuration: dict,
        recipient_email: str,
        subject: str,
        body: str,
        idempotency_key: str,
        timeout_seconds: float,
    ) -> NormalizedNotification:
        from_email = configuration.get("from_email") or credentials.get("username")
        if not from_email:
            raise IntegrationInvalidRequestError("No sender address is configured.")

        host = credentials.get("host")
        port = int(credentials.get("port", 587))
        validate_outbound_host(host, port)

        connection = get_connection(
            backend=_PINNED_SMTP_BACKEND,
            host=host,
            port=port,
            username=credentials.get("username"),
            password=credentials.get("password"),
            use_tls=bool(credentials.get("use_tls", True)),
            timeout=timeout_seconds,
        )
        message_id = make_msgid()
        message = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[recipient_email],
            connection=connection,
            headers={
                "Message-ID": message_id,
                # A stable, provider-visible dedupe hint — not itself relied
                # on for correctness (application-level idempotency via
                # Phase 6 + the caller's stable idempotency_key is what
                # actually prevents a duplicate send; section 60).
                "X-SupportPilot-Idempotency-Key": idempotency_key,
            },
        )
        try:
            connection.open()
            message.send(fail_silently=False)
        except smtplib.SMTPAuthenticationError as exc:
            raise IntegrationAuthenticationFailedError() from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise IntegrationInvalidRequestError("The recipient address was refused.") from exc
        except TimeoutError as exc:
            raise IntegrationTimeoutError() from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise IntegrationTemporarilyUnavailableError() from exc
        finally:
            connection.close()
        return NormalizedNotification(message_id=message_id, status="sent")
