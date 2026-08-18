"""Immutable audit trail for administrative and other sensitive actions.

Append-only by convention: there is no update/delete service and no
update/delete API. Never store secrets (passwords, JWTs, refresh tokens,
Authorization headers) in ``metadata`` — only structured, safe facts.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from common.models import BaseModel


class AuditAction(models.TextChoices):
    WORKSPACE_CREATED = "workspace.created", "Workspace created"
    WORKSPACE_UPDATED = "workspace.updated", "Workspace updated"
    WORKSPACE_MEMBER_ADDED = "workspace.member_added", "Member added"
    WORKSPACE_MEMBER_ROLE_CHANGED = "workspace.member_role_changed", "Member role changed"
    WORKSPACE_MEMBER_REMOVED = "workspace.member_removed", "Member removed"
    WORKSPACE_OWNERSHIP_TRANSFERRED = "workspace.ownership_transferred", "Ownership transferred"
    CUSTOMER_DEACTIVATED = "customer.deactivated", "Customer deactivated"
    CONVERSATION_ASSIGNED = "conversation.assigned", "Conversation assigned"
    CONVERSATION_REASSIGNED = "conversation.reassigned", "Conversation reassigned"
    CONVERSATION_CLOSED = "conversation.closed", "Conversation closed"
    CONVERSATION_REOPENED = "conversation.reopened", "Conversation reopened"
    TICKET_ASSIGNED = "ticket.assigned", "Ticket assigned"
    TICKET_REASSIGNED = "ticket.reassigned", "Ticket reassigned"
    TICKET_STATUS_CHANGED = "ticket.status_changed", "Ticket status changed"
    TICKET_RESOLVED = "ticket.resolved", "Ticket resolved"
    TICKET_REOPENED = "ticket.reopened", "Ticket reopened"


class AuditEvent(BaseModel):
    """A single immutable record of an administrative or sensitive action."""

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_events",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=64, choices=AuditAction.choices)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="audit_workspace_created_idx"),
            models.Index(fields=["action"], name="audit_action_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} on {self.target_type}:{self.target_id}"
