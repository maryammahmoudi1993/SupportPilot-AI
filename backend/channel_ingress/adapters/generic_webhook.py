"""Generic signed inbound webhook adapter (Phase 13 section 19, 23).

Defines SupportPilot's own deterministic, signed JSON envelope for a
provider-style inbound event — "a deterministic/generic signed provider
adapter is acceptable if adding a real vendor SDK is not justified" (section
23). A real vendor integration is a later, additive adapter behind the same
``ChannelAdapter`` protocol; nothing else in this app changes to add one.

Wire envelope (JSON body, canonical fields only — anything else is bounded,
safe metadata, never trusted structure):

    {
        "event_id": "<provider-stable event id>",
        "thread_id": "<provider thread/conversation id, optional>",
        "message_id": "<provider message id, optional>",
        "external_id": "<provider-stable sender identity>",
        "subject": "<optional subject>",
        "body": "<plain-text body>",
        "received_at": "<ISO-8601, optional — defaults to processing time>"
    }
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from integrations.crypto import CredentialEncryptionError, decrypt_credentials

from .. import models
from ..errors import PayloadInvalidError, UnsupportedEventError
from ..schemas import CanonicalInboundMessage
from ..security import enforce_body_size, verify_inbound_signature

_REQUIRED_STRING_FIELDS = ("event_id", "external_id", "body")
_MAX_FIELD_LENGTH = 4096


def _endpoint_signing_secret(endpoint: models.ChannelEndpoint) -> str:
    if not endpoint.encrypted_signing_secret:
        raise UnsupportedEventError()
    try:
        envelope = decrypt_credentials(endpoint.encrypted_signing_secret)
    except CredentialEncryptionError as exc:
        raise UnsupportedEventError() from exc
    secret = envelope.get("secret")
    if not isinstance(secret, str) or not secret:
        raise UnsupportedEventError()
    return secret


def _bounded_str(value: object, *, max_length: int = _MAX_FIELD_LENGTH) -> str:
    if not isinstance(value, str):
        raise PayloadInvalidError()
    return value[:max_length]


class GenericSignedWebhookAdapter:
    """The ``ChannelType.GENERIC_WEBHOOK`` adapter."""

    channel: str = models.ChannelType.GENERIC_WEBHOOK
    provider = "generic"
    #: Overridable per adapter (``EmailInboundAdapter`` requires ``from``
    #: instead of ``external_id`` — a different envelope field for the same
    #: role, section 23-25).
    required_fields: tuple[str, ...] = _REQUIRED_STRING_FIELDS

    def verify_signature(
        self, *, endpoint: models.ChannelEndpoint, raw_body: bytes, headers: Mapping[str, str]
    ) -> None:
        enforce_body_size(raw_body)
        secret = _endpoint_signing_secret(endpoint)
        verify_inbound_signature(
            secret=secret,
            raw_body=raw_body,
            timestamp_header=headers.get("X-SupportPilot-Timestamp"),
            signature_header=headers.get("X-SupportPilot-Signature"),
        )

    def parse_event(self, *, raw_body: bytes) -> dict:
        # Bounded, non-recursive JSON parsing only (section 22-23) — no
        # custom XML/YAML/pickle deserialization of any kind.
        try:
            parsed = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadInvalidError() from exc
        if not isinstance(parsed, dict):
            raise PayloadInvalidError()
        for field_name in self.required_fields:
            if not isinstance(parsed.get(field_name), str) or not parsed[field_name]:
                raise PayloadInvalidError()
        return parsed

    def _received_at(self, parsed: dict) -> datetime:
        raw = parsed.get("received_at")
        if not isinstance(raw, str) or not raw:
            return timezone.now()
        parsed_dt = parse_datetime(raw)
        if parsed_dt is None:
            return timezone.now()
        return parsed_dt if timezone.is_aware(parsed_dt) else timezone.make_aware(parsed_dt)

    def normalize(
        self, *, endpoint: models.ChannelEndpoint, parsed: dict
    ) -> CanonicalInboundMessage:
        body = _bounded_str(parsed["body"], max_length=settings.CHANNELS_MAX_MESSAGE_BODY_LENGTH)
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
            external_identity=_bounded_str(parsed["external_id"], max_length=255),
            subject=_bounded_str(parsed.get("subject") or "", max_length=300),
            body=body,
            received_at=self._received_at(parsed),
        )
