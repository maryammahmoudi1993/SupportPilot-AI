"""Conversation and message domain models.

A ``Conversation`` represents a support interaction with a customer.
``Message`` is the immutable historical event stream of a conversation —
never a temporary chat UI object.

Provider-specific channel values (gmail, twilio, intercom, zendesk, ...) are
deliberately out of scope: those belong to later integration phases. The
``channel``, ``external_id``, and ``metadata`` fields exist only so those
phases can be added without a redesign of this core model.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models

from common.models import BaseModel


class ConversationChannel(models.TextChoices):
    WEB = "web", "Web"
    CHAT = "chat", "Chat"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    API = "api", "API"


class ConversationStatus(models.TextChoices):
    OPEN = "open", "Open"
    PENDING = "pending", "Pending"
    CLOSED = "closed", "Closed"


class Conversation(BaseModel):
    """A support interaction with a customer. Status transitions are
    implemented through the service layer (see ``conversations.services``),
    never through unrestricted field mutation."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="conversations"
    )
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.CASCADE, related_name="conversations"
    )
    channel = models.CharField(
        max_length=16, choices=ConversationChannel.choices, default=ConversationChannel.WEB
    )
    status = models.CharField(
        max_length=16, choices=ConversationStatus.choices, default=ConversationStatus.OPEN
    )
    subject = models.CharField(max_length=300, blank=True)
    assigned_to = models.ForeignKey(
        "workspaces.WorkspaceMembership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_conversations",
    )
    external_id = models.CharField(max_length=255, null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "external_id"],
                condition=models.Q(external_id__isnull=False),
                name="uniq_conversation_workspace_external_id",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"], name="conv_ws_status_idx"),
            models.Index(fields=["workspace", "customer"], name="conv_ws_customer_idx"),
            models.Index(fields=["workspace", "assigned_to"], name="conv_ws_assignee_idx"),
            models.Index(fields=["workspace", "-last_message_at"], name="conv_ws_lastmsg_idx"),
        ]

    def __str__(self) -> str:
        return self.subject or f"Conversation {self.id}"

    def clean(self) -> None:
        # Defense-in-depth: the service layer is the primary enforcement
        # point, but direct ORM/admin usage must not be able to create a
        # cross-tenant relationship either.
        if self.customer_id and self.customer.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"customer": "Customer must belong to the same workspace as the conversation."}
            )
        assignee = self.assigned_to
        if assignee is not None and assignee.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"assigned_to": "Assignee must belong to the same workspace as the conversation."}
            )

    def save(self, *args, **kwargs):
        self.subject = (self.subject or "").strip()
        if self.external_id is not None:
            self.external_id = self.external_id.strip() or None
        super().save(*args, **kwargs)


class MessageSenderType(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    HUMAN_AGENT = "human_agent", "Human Agent"
    AI_AGENT = "ai_agent", "AI Agent"
    SYSTEM = "system", "System"


class MessageDirection(models.TextChoices):
    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"
    INTERNAL = "internal", "Internal"


class Message(BaseModel):
    """One historical event in a conversation. Immutable after creation —
    there is deliberately no update/delete API or service."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="messages"
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender_type = models.CharField(max_length=16, choices=MessageSenderType.choices)
    sender_membership = models.ForeignKey(
        "workspaces.WorkspaceMembership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
        help_text="Set for human_agent messages; null for customer/system/ai_agent messages.",
    )
    direction = models.CharField(max_length=16, choices=MessageDirection.choices)
    body = models.TextField()
    external_id = models.CharField(max_length=255, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    # Phase 16 Part F (section 33): a strictly-increasing, DB-assigned
    # insertion sequence, kept alongside ``created_at`` purely as a
    # deterministic ordering tie-breaker. ``id`` (BaseModel's UUID primary
    # key) is *not* a safe tie-breaker for creation order — it is random,
    # not monotonic — so two messages sharing the same ``created_at``
    # (a real, if rare, possibility: ``auto_now_add`` resolves to whatever
    # precision the DB timestamp column and the Python clock both give it)
    # previously sorted in effectively random relative order. That silently
    # broke the "newest history is retained" guarantee
    # ``agents.context.build_conversation_context`` depends on — reproduced
    # concretely as the older of two same-instant messages sometimes
    # surviving a context-window trim instead of the newer one.
    sequence = models.BigIntegerField(
        unique=True,
        editable=False,
        db_default=models.Func(
            models.Value("conversations_message_sequence_seq"), function="nextval"
        ),
    )

    class Meta:
        ordering = ["created_at", "sequence"]
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="msg_conv_created_idx"),
            models.Index(fields=["workspace", "created_at"], name="msg_ws_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.sender_type}/{self.direction} message on {self.conversation_id}"

    def clean(self) -> None:
        if self.conversation_id and self.conversation.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"conversation": "Conversation must belong to the same workspace as the message."}
            )
        sender = self.sender_membership
        if sender is not None and sender.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"sender_membership": "Sender must belong to the same workspace as the message."}
            )
