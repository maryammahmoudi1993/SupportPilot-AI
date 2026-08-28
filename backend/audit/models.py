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
    KNOWLEDGE_SOURCE_CREATED = "knowledge.source_created", "Knowledge source created"
    KNOWLEDGE_SOURCE_UPDATED = "knowledge.source_updated", "Knowledge source updated"
    KNOWLEDGE_SOURCE_DEACTIVATED = (
        "knowledge.source_deactivated",
        "Knowledge source deactivated",
    )
    KNOWLEDGE_DOCUMENT_UPLOADED = (
        "knowledge.document_uploaded",
        "Knowledge document uploaded",
    )
    KNOWLEDGE_DOCUMENT_RETRY_REQUESTED = (
        "knowledge.document_retry_requested",
        "Knowledge document retry requested",
    )
    AGENT_DEFINITION_CREATED = "agent.definition_created", "Agent definition created"
    AGENT_DEFINITION_UPDATED = "agent.definition_updated", "Agent definition updated"
    AGENT_VERSION_CREATED = "agent.version_created", "Agent version created"
    AGENT_VERSION_PUBLISHED = "agent.version_published", "Agent version published"
    AGENT_RUN_STARTED = "agent.run_started", "Agent run started"
    AGENT_RUN_CANCELLED = "agent.run_cancelled", "Agent run cancelled"
    AGENT_RUN_FAILED = "agent.run_failed", "Agent run failed"
    AGENT_RUN_COMPLETED = "agent.run_completed", "Agent run completed"
    AGENT_RUN_HANDED_OFF = "agent.run_handed_off", "Agent run handed off"
    TOOL_BINDING_CREATED = "tool.binding_created", "Tool binding created"
    TOOL_BINDING_UPDATED = "tool.binding_updated", "Tool binding updated"
    TOOL_BINDING_DISABLED = "tool.binding_disabled", "Tool binding disabled"
    INTEGRATION_CONNECTION_CREATED = (
        "integration.connection_created",
        "Integration connection created",
    )
    INTEGRATION_CONNECTION_UPDATED = (
        "integration.connection_updated",
        "Integration connection updated",
    )
    INTEGRATION_CREDENTIALS_ROTATED = (
        "integration.credentials_rotated",
        "Integration credentials rotated",
    )
    INTEGRATION_CONNECTION_DISABLED = (
        "integration.connection_disabled",
        "Integration connection disabled",
    )
    INTEGRATION_CONNECTION_ENABLED = (
        "integration.connection_enabled",
        "Integration connection enabled",
    )
    INTEGRATION_CONNECTION_TESTED = (
        "integration.connection_tested",
        "Integration connection tested",
    )
    PAYMENT_REFUND_EXECUTED = "payment.refund_executed", "Payment refund executed"
    POLICY_CREATED = "policy.created", "Policy created"
    POLICY_UPDATED = "policy.updated", "Policy updated"
    POLICY_VERSION_CREATED = "policy.version_created", "Policy version created"
    POLICY_VERSION_PUBLISHED = "policy.version_published", "Policy version published"
    POLICY_ACTIVATED = "policy.activated", "Policy activated"
    POLICY_DEACTIVATED = "policy.deactivated", "Policy deactivated"
    POLICY_ACTION_DENIED = "policy.action_denied", "Action denied by policy"
    APPROVAL_REQUESTED = "approval.requested", "Approval requested"
    APPROVAL_APPROVED = "approval.approved", "Approval approved"
    APPROVAL_REJECTED = "approval.rejected", "Approval rejected"
    APPROVAL_EXPIRED = "approval.expired", "Approval expired"
    APPROVAL_CANCELLED = "approval.cancelled", "Approval cancelled"
    HUMAN_HANDOFF_CREATED = "human_handoff.created", "Human handoff created"
    HUMAN_HANDOFF_ASSIGNED = "human_handoff.assigned", "Human handoff assigned"
    HUMAN_HANDOFF_RESOLVED = "human_handoff.resolved", "Human handoff resolved"
    HUMAN_HANDOFF_CANCELLED = "human_handoff.cancelled", "Human handoff cancelled"
    WEBHOOK_ENDPOINT_CREATED = "webhook_endpoint.created", "Webhook endpoint created"
    WEBHOOK_ENDPOINT_UPDATED = "webhook_endpoint.updated", "Webhook endpoint updated"
    WEBHOOK_ENDPOINT_DISABLED = "webhook_endpoint.disabled", "Webhook endpoint disabled"
    WEBHOOK_SECRET_ROTATED = "webhook_endpoint.secret_rotated", "Webhook signing secret rotated"
    WEBHOOK_DELIVERY_REDRIVEN = (
        "webhook_delivery.manually_redriven",
        "Webhook delivery manually redriven",
    )


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
