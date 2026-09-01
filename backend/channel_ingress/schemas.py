"""The canonical inbound message contract (Phase 13 section 7).

Every channel adapter's ``normalize`` step terminates here. Nothing past
this boundary — identity resolution, conversation resolution, message
persistence, orchestration — ever sees a raw provider dict or transport
request object again (section 7-8). A ``frozen`` dataclass rather than a
Pydantic model, matching this codebase's existing convention for internal,
already-validated value objects (see ``agents.context.ConversationContext``)
— Pydantic is reserved for boundary validation (serializers, tool I/O
schemas), which the adapter's ``parse_event`` step already performed before
this object is constructed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CanonicalInboundMessage:
    """A channel- and provider-agnostic inbound customer message.

    ``external_identity`` is the normalized, channel-scoped identity string
    (a lower-cased email for EMAIL, an opaque per-session visitor id for
    WEB_CHAT) that ``channel_ingress.identity`` resolves against — never a
    raw, unnormalized provider field. ``metadata`` carries only small, bounded
    safe fields (section 43) — never an unlimited provider payload.
    """

    channel: str
    provider: str
    provider_event_id: str
    external_identity: str
    body: str
    received_at: datetime
    provider_thread_id: str | None = None
    provider_message_id: str | None = None
    subject: str = ""
    reply_context: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)
