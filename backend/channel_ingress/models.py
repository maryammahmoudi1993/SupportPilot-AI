"""Multi-channel ingress domain models (Phase 13).

Every channel — web chat, a signed generic/email-style provider webhook, and
(deferred, see ``docs/architecture/multichannel-ingress.md``) voice — funnels
through the same three durable rows defined here rather than a
per-channel schema:

* ``ChannelEndpoint`` — one workspace-owned, explicitly-typed inbound
  configuration (which agent handles it, which ``IntegrationConnection``
  supplies outbound credentials, its signing secret). The public routing
  identifier for every public ingress URL; never itself a secret.
* ``InboundChannelEvent`` — one durable row per logical inbound provider
  event, the dedupe/state-machine identity described in section 9-11 of the
  Phase 13 brief. Deliberately *not* a general event-sourcing framework: it
  carries only enough state to make "have we already processed this
  logical event" and "did we succeed" a database fact, plus the safe,
  bounded provider identifiers needed for thread/message correlation.
* ``ChatSession`` — the bounded, opaque-token public-security primitive for
  an anonymous web-chat visitor (section 17-18). A capability, not an
  identity: it proves "this caller may act as this chat session", never
  "this caller is this Customer".

Response routing back out to a channel reuses the Phase 10 ``Delivery``
engine — see ``channel_ingress/response_delivery.py`` and its
``ChannelResponseDelivery`` companion model below, which mirrors
``notifications.models.NotificationDelivery`` exactly, keyed by the
customer-visible output ``Message`` instead of a ``ToolExecution``.
"""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models

from common.models import BaseModel


class ChannelType(models.TextChoices):
    """Server-owned, bounded transport types (section 6-7). Never an
    arbitrary provider-supplied string — a new channel type is a deliberate
    code change, never data."""

    WEB_CHAT = "web_chat", "Web chat"
    EMAIL = "email", "Email"
    GENERIC_WEBHOOK = "generic_webhook", "Generic signed webhook"


class ChannelEndpointStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class UnknownCustomerPolicy(models.TextChoices):
    """Section 28: an explicit, per-endpoint policy for an inbound identity
    that does not match any existing ``Customer`` in the workspace — never
    left for each adapter to invent independently."""

    CREATE = "create", "Create a new customer record"
    REJECT = "reject", "Reject the event"


class ChannelEndpoint(BaseModel):
    """A workspace-owned inbound channel configuration. ``id`` is the public
    routing identifier used in every public ingress URL (mirroring
    ``webhooks.WebhookEndpoint``'s ``endpoint_id``) — safe to expose: it only
    selects *which* endpoint's normalization/identity rules apply, and is
    never by itself sufficient authorization to reach another workspace's
    data (section 15, 17, 45)."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="channel_endpoints"
    )
    channel = models.CharField(max_length=20, choices=ChannelType.choices)
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20, choices=ChannelEndpointStatus.choices, default=ChannelEndpointStatus.ACTIVE
    )

    # The single agent version that handles every inbound message on this
    # endpoint (section 33 analog: an explicit, bounded binding rather than
    # an ambiguous "default agent for the workspace" lookup). PROTECT: an
    # agent version with a live channel binding can never be deleted out
    # from under it.
    agent_version = models.ForeignKey(
        "agents.AgentVersion", on_delete=models.PROTECT, related_name="channel_endpoints"
    )

    # Reused, never duplicated (section 15): the encrypted credentials an
    # EMAIL endpoint's outbound response delivery sends through. Optional —
    # a GENERIC_WEBHOOK/WEB_CHAT endpoint never needs one.
    integration_connection = models.ForeignKey(
        "integrations.IntegrationConnection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="channel_endpoints",
    )

    unknown_customer_policy = models.CharField(
        max_length=16,
        choices=UnknownCustomerPolicy.choices,
        default=UnknownCustomerPolicy.CREATE,
    )

    # Versioned encrypted signing-secret envelope (Fernet via
    # ``integrations.crypto``, reused unchanged — section 15) for
    # GENERIC_WEBHOOK/EMAIL inbound signature verification. Blank for
    # WEB_CHAT, which uses session-capability security instead (section 17,
    # 45), never a signature. Never exposed through any serializer.
    encrypted_signing_secret = models.TextField(blank=True)
    secret_created_at = models.DateTimeField(null=True, blank=True)

    # Non-secret, bounded routing configuration only (e.g. the email
    # endpoint's own routing address, a webchat widget's display title).
    # Validated per-channel before save — see ``channel_ingress.services``.
    configuration = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_channel_endpoints",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""), name="channel_endpoint_name_not_blank"
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"], name="chan_ep_ws_status_idx"),
            models.Index(fields=["workspace", "channel"], name="chan_ep_ws_channel_idx"),
        ]

    def __str__(self) -> str:
        # Deliberately excludes secret material — safe even in shells/logs.
        return f"{self.workspace_id}:{self.channel}:{self.status}"

    @property
    def enabled(self) -> bool:
        return self.status == ChannelEndpointStatus.ACTIVE

    @property
    def secret_configured(self) -> bool:
        return bool(self.encrypted_signing_secret)


class InboundChannelEventStatus(models.TextChoices):
    """Section 10: an explicit, bounded four-state lifecycle — never dozens
    of operational states, and never mutable through the API (state
    transitions are service-only, see ``channel_ingress.services``)."""

    RECEIVED = "received", "Received"
    PROCESSING = "processing", "Processing"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"


class InboundChannelEvent(BaseModel):
    """One durable row per logical inbound provider event (section 9).

    The dedupe identity (section 11) is the database-unique
    ``(endpoint, provider_event_id)`` pair — ``endpoint`` alone already
    scopes by workspace, channel, and provider, so this single constraint is
    section 11's full "workspace/channel endpoint + provider +
    provider_event_id" boundary without needing three separate columns in
    the key. ``payload_digest`` (a SHA-256 hex digest of the canonical raw
    request bytes — never the bytes themselves, section 8) is what lets
    ``channel_ingress.services.ingest_channel_event`` distinguish a genuine
    duplicate delivery of the *same* logical event (idempotent no-op) from a
    different logical event that happens to reuse a provider event id
    (``idempotency_conflict`` — section 12).
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="inbound_channel_events"
    )
    endpoint = models.ForeignKey(
        ChannelEndpoint, on_delete=models.PROTECT, related_name="inbound_events"
    )
    provider_event_id = models.CharField(max_length=255)
    provider_thread_id = models.CharField(max_length=255, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    payload_digest = models.CharField(max_length=64)

    # The already-normalized canonical fields the async processing worker
    # needs (section 34: "Celery/service resolves identity/conversation/
    # message" — it cannot re-derive them from nothing). Deliberately
    # *not* the raw provider payload (section 8): only the same bounded,
    # normalized content that becomes this event's ``Customer``-identity key
    # and ``Message.body`` moments later, never headers, signatures, or
    # arbitrary provider structure.
    external_identity = models.CharField(max_length=255)
    subject = models.CharField(max_length=300, blank=True)
    body = models.TextField()

    status = models.CharField(
        max_length=16,
        choices=InboundChannelEventStatus.choices,
        default=InboundChannelEventStatus.RECEIVED,
    )
    failure_code = models.CharField(max_length=64, blank=True)

    conversation = models.ForeignKey(
        "conversations.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_channel_events",
    )
    # One inbound event produces at most one customer Message (section 11) —
    # a ``OneToOneField`` makes that a database invariant, exactly mirroring
    # ``AgentRun.trigger_message``.
    message = models.OneToOneField(
        "conversations.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_channel_event",
    )

    received_at = models.DateTimeField(auto_now_add=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "provider_event_id"],
                name="uniq_inbound_event_endpoint_provider_event_id",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="chan_evt_ws_created_idx"),
            models.Index(fields=["endpoint", "provider_thread_id"], name="chan_evt_ep_thread_idx"),
            models.Index(fields=["status", "received_at"], name="chan_evt_status_recv_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.id}:{self.endpoint_id}:{self.status}"


def _generate_session_token() -> str:
    """Server-generated, cryptographically secure web-chat session
    capability (section 17) — 256 bits from ``secrets``, mirroring
    ``webhooks.signing.generate_signing_secret``."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Only this hash is ever persisted (section 17) — the plaintext token
    is returned to the client exactly once, at session-bootstrap time, and
    never stored or logged."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ChatSession(BaseModel):
    """One anonymous web-chat visitor's bounded session capability (section
    17-18). Proves "this caller may act as this session" — never a claim
    about *who* the caller is; that is ``customer``'s job, resolved once via
    ``channel_ingress.identity`` and then reused for the life of the
    session."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="chat_sessions"
    )
    endpoint = models.ForeignKey(
        ChannelEndpoint, on_delete=models.CASCADE, related_name="chat_sessions"
    )
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_sessions",
    )
    conversation = models.OneToOneField(
        "conversations.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_session",
    )

    # Only the hash is ever persisted (section 17) — see
    # ``hash_session_token``. Unique so a lookup is a single indexed
    # equality query, and so a hash collision (astronomically unlikely, but
    # never silently tolerated) fails loudly instead of granting a session
    # to the wrong row.
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="chat_sess_ws_created_idx"),
        ]

    def __str__(self) -> str:
        # Deliberately excludes the token/hash — safe even in shells/logs.
        return f"{self.id}:{self.workspace_id}:{self.endpoint_id}"


class ChannelResponseDelivery(BaseModel):
    """The channel-response-specific one-to-one companion to a Phase 10
    ``Delivery`` (mirrors ``notifications.models.NotificationDelivery``
    exactly, section 40): everything the generic delivery lifecycle doesn't
    need to know about — the frozen destination/content snapshot and the
    stable provider-facing idempotency identity.

    Keyed by the customer-visible output ``Message`` (a ``OneToOneField``,
    the database-enforced "at most one outbound routing per agent reply"
    invariant, section 11) rather than a ``ToolExecution`` — an agent reply
    routes to a channel automatically, it is never an explicit tool call.
    Never stores provider credentials (section 43) — only the same
    non-secret destination/subject/body a human already sees in the
    Message/Conversation record.
    """

    delivery = models.OneToOneField(
        "notifications.Delivery", on_delete=models.CASCADE, related_name="channel_response_delivery"
    )
    source_message = models.OneToOneField(
        "conversations.Message", on_delete=models.PROTECT, related_name="channel_response_delivery"
    )
    endpoint = models.ForeignKey(
        ChannelEndpoint, on_delete=models.PROTECT, related_name="response_deliveries"
    )

    # Frozen at creation time (section 43) — never re-read from a possibly
    # since-mutated Conversation/Customer record on retry.
    destination_address = models.CharField(max_length=320)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    # The provider thread/message reference this response replies into
    # (section 42) — frozen from the conversation's channel metadata at
    # creation time, never re-derived on retry.
    thread_reference = models.CharField(max_length=255, blank=True)

    # The stable identity passed to the provider on every attempt for this
    # delivery (section 40, mirrors ``NotificationDelivery.idempotency_key``)
    # — never regenerated per retry.
    idempotency_key = models.CharField(max_length=200)
    provider_message_id = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(destination_address=""),
                name="channel_response_delivery_destination_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(idempotency_key=""),
                name="channel_response_delivery_idempotency_key_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.delivery_id}:{self.endpoint_id}"
