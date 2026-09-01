"""Signed email-style inbound adapter (Phase 13 section 23-25).

Reuses ``GenericSignedWebhookAdapter``'s signature verification and JSON
parsing unchanged — only the envelope's field names and the
provider->canonical mapping differ. Wire envelope (JSON body):

    {
        "event_id": "<provider-stable event id>",
        "thread_id": "<provider thread/reference id, optional>",
        "message_id": "<provider message id, optional>",
        "from": "<sender email address>",
        "subject": "<optional subject>",
        "body": "<plain-text body>",
        "body_html": "<optional HTML body — untrusted, never normalized as
            the trusted body; recorded only as a bounded presence flag>",
        "received_at": "<ISO-8601, optional>"
    }

A signed envelope authenticates the *provider delivery* — never that the
``from`` address is a real, verified identity belonging to a specific
existing customer (section 25). ``channel_ingress.identity`` treats it as
exactly what it is: an inbound-provider-supplied identity string, resolved
through the same bounded, explicit rules every other channel uses — never a
free pass to silently link to or create cross-workspace state.
"""

from __future__ import annotations

from django.conf import settings

from ..errors import PayloadInvalidError
from ..models import ChannelType
from ..schemas import CanonicalInboundMessage
from .generic_webhook import GenericSignedWebhookAdapter, _bounded_str

#: Deliberately minimal — full RFC 5322 validation is not this adapter's
#: job; it only needs to reject an obviously-malformed sender field before
#: normalizing it as an identity key (section 25).
_MIN_EMAIL_LENGTH = 3


def _normalize_email(value: object) -> str:
    if not isinstance(value, str):
        raise PayloadInvalidError()
    normalized = value.strip().lower()
    if len(normalized) < _MIN_EMAIL_LENGTH or "@" not in normalized or normalized.startswith("@"):
        raise PayloadInvalidError()
    return normalized[:320]


class EmailInboundAdapter(GenericSignedWebhookAdapter):
    """The ``ChannelType.EMAIL`` adapter. Uses its own envelope field name
    (``from``, not the generic adapter's ``external_id``) for the sender
    identity, so ``normalize`` is its own implementation rather than a call
    into the generic adapter's (which indexes ``external_id`` directly)."""

    channel: str = ChannelType.EMAIL
    provider = "generic_email"
    required_fields = ("event_id", "from", "body")

    def normalize(self, *, endpoint, parsed: dict) -> CanonicalInboundMessage:
        sender = _normalize_email(parsed["from"])
        body = _bounded_str(parsed["body"], max_length=settings.CHANNELS_MAX_MESSAGE_BODY_LENGTH)
        # HTML, if present at all, is untrusted content/data (section 23) —
        # never normalized into the trusted plain-text body. Only a bounded
        # presence flag is recorded so an operator can see it existed.
        metadata: dict[str, str] = {}
        if parsed.get("body_html"):
            metadata["had_html_body"] = "true"
        return CanonicalInboundMessage(
            channel=self.channel,
            provider=self.provider,
            provider_event_id=_bounded_str(parsed["event_id"], max_length=255),
            provider_thread_id=(
                _bounded_str(parsed["thread_id"], max_length=255)
                if parsed.get("thread_id")
                else None
            ),
            provider_message_id=(
                _bounded_str(parsed["message_id"], max_length=255)
                if parsed.get("message_id")
                else None
            ),
            external_identity=sender,
            subject=_bounded_str(parsed.get("subject") or "", max_length=300),
            body=body,
            received_at=self._received_at(parsed),
            metadata=metadata,
        )
