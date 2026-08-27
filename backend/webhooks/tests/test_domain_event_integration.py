"""Domain event integration (Phase 10 Block 3, section 47-49): the four
approval-lifecycle transitions and human-handoff creation each emit exactly
one safe webhook event, and an approver's private comment never enters the
payload (section 48)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from accounts.tests.factories import UserFactory
from approvals.models import ApprovalDecisionValue, ApprovalRequest
from approvals.services import decide_approval, expire_stale_approvals
from approvals.tests.factories import pending_refund_approval
from webhooks.models import WebhookEvent, WebhookEventType
from webhooks.tests.factories import WebhookEndpointFactory
from workspaces.models import WorkspaceMembership, WorkspaceRole

pytestmark = pytest.mark.django_db(transaction=True)


def _approver_for(workspace):
    user = UserFactory()
    WorkspaceMembership.objects.create(
        workspace=workspace, user=user, role=WorkspaceRole.OWNER, is_active=True
    )
    return user


def test_approval_requested_emits_safe_webhook_event(monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    WebhookEndpointFactory(
        workspace=run.workspace, subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED]
    )

    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_REQUESTED
    )
    assert event.payload_snapshot["approval_id"] == str(approval.id)
    assert "arguments" not in event.payload_snapshot
    assert "safe_context" not in event.payload_snapshot


def test_approval_approved_emits_event_without_private_comment(monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    approver = _approver_for(run.workspace)
    secret_comment = "internal note: customer is a known fraud risk, do not disclose"

    decide_approval(
        workspace=run.workspace,
        approval_request=approval,
        actor=approver,
        actor_role=WorkspaceRole.OWNER,
        decision=ApprovalDecisionValue.APPROVE,
        comment=secret_comment,
    )

    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_APPROVED
    )
    assert event.payload_snapshot["approval_id"] == str(approval.id)
    assert secret_comment not in str(event.payload_snapshot)
    assert "comment" not in event.payload_snapshot


def test_approval_rejected_emits_event_without_private_comment(monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    approver = _approver_for(run.workspace)
    secret_comment = "internal note: reject silently, do not tell customer why"

    decide_approval(
        workspace=run.workspace,
        approval_request=approval,
        actor=approver,
        actor_role=WorkspaceRole.OWNER,
        decision=ApprovalDecisionValue.REJECT,
        comment=secret_comment,
    )

    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_REJECTED
    )
    assert secret_comment not in str(event.payload_snapshot)
    assert "comment" not in event.payload_snapshot


def test_approval_expired_emits_safe_webhook_event(monkeypatch):
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    approval.refresh_from_db()
    ApprovalRequest.objects.filter(pk=approval.pk).update(
        expires_at=approval.created_at + timedelta(milliseconds=1)
    )

    expire_stale_approvals()

    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_EXPIRED
    )
    assert event.payload_snapshot["approval_id"] == str(approval.id)


def test_handoff_created_emits_safe_webhook_event(monkeypatch):
    from conversations.tests.factories import ConversationFactory
    from tickets.services import create_or_reuse_handoff

    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    conversation = ConversationFactory()
    handoff, created = create_or_reuse_handoff(
        workspace=conversation.workspace,
        conversation=conversation,
        reason_code="low_confidence",
        safe_summary="Customer asked about a refund the agent could not resolve.",
    )
    assert created is True

    event = WebhookEvent.objects.get(
        workspace=conversation.workspace, event_type=WebhookEventType.HANDOFF_CREATED
    )
    assert event.payload_snapshot["handoff_id"] == str(handoff.id)
    assert event.payload_snapshot["summary"] == handoff.safe_summary
