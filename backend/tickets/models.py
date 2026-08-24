"""Ticket domain model.

A ``Ticket`` is a structured support work item requiring tracking and
resolution. It may originate from a conversation but does not require one —
it always belongs to a customer.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models

from common.models import BaseModel


class TicketStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    PENDING = "pending", "Pending"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class TicketPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Ticket(BaseModel):
    """A structured support work item. Status transitions are implemented
    through the service layer (see ``tickets.services``), never through
    unrestricted field mutation."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="tickets"
    )
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.CASCADE, related_name="tickets"
    )
    conversation = models.ForeignKey(
        "conversations.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    subject = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=TicketStatus.choices, default=TicketStatus.OPEN
    )
    priority = models.CharField(
        max_length=16, choices=TicketPriority.choices, default=TicketPriority.NORMAL
    )
    assigned_to = models.ForeignKey(
        "workspaces.WorkspaceMembership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status"], name="tick_ws_status_idx"),
            models.Index(fields=["workspace", "priority"], name="tick_ws_priority_idx"),
            models.Index(fields=["workspace", "customer"], name="tick_ws_customer_idx"),
            models.Index(fields=["workspace", "assigned_to"], name="tick_ws_assignee_idx"),
        ]

    def __str__(self) -> str:
        return self.subject

    def clean(self) -> None:
        if self.customer_id and self.customer.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"customer": "Customer must belong to the same workspace as the ticket."}
            )
        conversation = self.conversation
        if conversation is not None and conversation.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"conversation": "Conversation must belong to the same workspace as the ticket."}
            )
        assignee = self.assigned_to
        if assignee is not None and assignee.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"assigned_to": "Assignee must belong to the same workspace as the ticket."}
            )

    def save(self, *args, **kwargs):
        self.subject = (self.subject or "").strip()
        self.description = self.description or ""
        super().save(*args, **kwargs)


class HumanHandoffStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ASSIGNED = "assigned", "Assigned"
    RESOLVED = "resolved", "Resolved"
    CANCELLED = "cancelled", "Cancelled"


HUMAN_HANDOFF_ACTIVE_STATUSES = frozenset({HumanHandoffStatus.PENDING, HumanHandoffStatus.ASSIGNED})


class HumanHandoffReason(models.TextChoices):
    CUSTOMER_REQUESTED = "customer_requested", "Customer requested a human"
    UNSUPPORTED_ACTION = "unsupported_action", "Unsupported action"
    RUNTIME_FAILURE = "runtime_failure", "Repeated bounded runtime failure"
    LOW_CONFIDENCE = "low_confidence", "Low-confidence retrieval/response"
    POLICY_ESCALATION = "policy_escalation", "Business workflow requires an operator"


class HumanHandoff(BaseModel):
    """A deliberate exit from agent orchestration to a human operator
    (Phase 9). Carries only safe, structured facts — never hidden model
    reasoning (see ``docs/architecture/full-agent-orchestration.md``). Does
    not grant the LLM new privileges: creating a handoff is itself a bounded,
    server-validated capability, not an authorization override."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="human_handoffs"
    )
    conversation = models.ForeignKey(
        "conversations.Conversation", on_delete=models.CASCADE, related_name="human_handoffs"
    )
    agent_run = models.ForeignKey(
        "agents.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="human_handoffs",
    )
    ticket = models.ForeignKey(
        Ticket, on_delete=models.SET_NULL, null=True, blank=True, related_name="human_handoffs"
    )
    status = models.CharField(
        max_length=16, choices=HumanHandoffStatus.choices, default=HumanHandoffStatus.PENDING
    )
    reason_code = models.CharField(max_length=32, choices=HumanHandoffReason.choices)
    safe_summary = models.CharField(max_length=500)
    assigned_to = models.ForeignKey(
        "workspaces.WorkspaceMembership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_handoffs",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Idempotency (section 51 of the Phase 9 brief): a conversation
            # may have at most one *active* handoff at a time. A partial
            # unique index (rather than an application-only check) makes a
            # concurrent double-create safe under load, not just in the
            # common case.
            models.UniqueConstraint(
                fields=["conversation"],
                # A fixed, explicitly ordered tuple — never derived from
                # ``HUMAN_HANDOFF_ACTIVE_STATUSES`` (a frozenset) directly,
                # whose iteration order is not stable across interpreter
                # runs and would otherwise make every fresh
                # ``makemigrations`` see a spurious constraint change.
                condition=models.Q(
                    status__in=(HumanHandoffStatus.PENDING, HumanHandoffStatus.ASSIGNED)
                ),
                name="handoff_one_active_per_conversation",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "status", "-created_at"], name="handoff_ws_status_idx"
            ),
            models.Index(fields=["conversation", "status"], name="handoff_conv_status_idx"),
        ]

    def clean(self) -> None:
        if self.conversation_id and self.conversation.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"conversation": "Conversation must belong to the same workspace as the handoff."}
            )
        agent_run = self.agent_run
        if agent_run is not None and agent_run.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"agent_run": "Agent run must belong to the same workspace as the handoff."}
            )
        ticket = self.ticket
        if ticket is not None and ticket.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"ticket": "Ticket must belong to the same workspace as the handoff."}
            )
        assignee = self.assigned_to
        if assignee is not None and assignee.workspace_id != self.workspace_id:
            raise DjangoValidationError(
                {"assigned_to": "Assignee must belong to the same workspace as the handoff."}
            )

    def save(self, *args, **kwargs) -> None:
        self.safe_summary = (self.safe_summary or "").strip()[:500]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.id}:{self.status}"
