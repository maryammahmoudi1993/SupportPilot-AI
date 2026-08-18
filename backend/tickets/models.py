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
