"""Transactional durability of domain-event production (Phase 10 Block 3
remediation, section 6-11).

Required invariant: if the domain event is considered committed, the
durable ``WebhookEvent``/``WebhookDelivery`` records must already be part
of the *same* committed database transaction as the authoritative business
mutation that produces them — never created only by a later
``transaction.on_commit`` callback (that mechanism is reserved for
best-effort Celery publication only, which may safely fail without losing
anything already committed).
"""

from __future__ import annotations

import pytest
from django.db import transaction

from accounts.tests.factories import UserFactory
from approvals.models import ApprovalDecisionValue, ApprovalStatus
from approvals.services import decide_approval
from approvals.tests.factories import pending_refund_approval
from notifications.models import Delivery, DeliveryAttempt, DeliveryStatus
from webhooks.models import WebhookDelivery, WebhookEvent, WebhookEventType
from webhooks.services import emit_event
from webhooks.tests.factories import WebhookEndpointFactory
from workspaces.models import WorkspaceMembership, WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db(transaction=True)


def _owner_for(workspace):
    user = UserFactory()
    WorkspaceMembership.objects.create(
        workspace=workspace, user=user, role=WorkspaceRole.OWNER, is_active=True
    )
    return user


# ---------------------------------------------------------------------------
# Primitive-level proof (section 8)
# ---------------------------------------------------------------------------


def test_emit_event_rolls_back_with_its_calling_transaction():
    """``emit_event``'s own writes are not a side channel — they roll back
    exactly like any other write in the same transaction when that
    transaction never commits."""
    workspace = WorkspaceFactory()
    WebhookEndpointFactory(
        workspace=workspace, subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED]
    )

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with transaction.atomic():
            emit_event(
                workspace=workspace, event_type=WebhookEventType.APPROVAL_REQUESTED, data={"x": 1}
            )
            raise Boom()

    assert not WebhookEvent.objects.filter(workspace=workspace).exists()
    assert not WebhookDelivery.objects.filter(workspace=workspace).exists()
    assert not Delivery.objects.filter(workspace=workspace).exists()


# ---------------------------------------------------------------------------
# Real approval-lifecycle commit atomicity (section 7)
# ---------------------------------------------------------------------------


def test_approval_decision_commits_state_event_and_delivery_together(monkeypatch):
    """After a real ``decide_approval()`` call commits, the approval state,
    ``WebhookEvent``, and ``WebhookDelivery`` all exist together — proving
    event production happened inside that same commit, not a later
    callback."""
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    WebhookEndpointFactory(
        workspace=run.workspace, subscribed_event_types=[WebhookEventType.APPROVAL_APPROVED]
    )
    owner = _owner_for(run.workspace)

    decide_approval(
        workspace=run.workspace,
        approval_request=approval,
        actor=owner,
        actor_role=WorkspaceRole.OWNER,
        decision=ApprovalDecisionValue.APPROVE,
    )

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.APPROVED
    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_APPROVED
    )
    webhook_delivery = WebhookDelivery.objects.get(event=event)
    assert webhook_delivery.delivery.status == DeliveryStatus.PENDING


def test_broker_failure_during_approval_transaction_never_loses_committed_state(monkeypatch):
    """A Celery publication failure (the ``transaction.on_commit`` callback,
    which only runs *after* the transaction above already committed) must
    never erase or fail the already-committed approval/event/delivery
    state, and must never consume an HTTP attempt slot."""
    import notifications.tasks as tasks_module

    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    WebhookEndpointFactory(
        workspace=run.workspace, subscribed_event_types=[WebhookEventType.APPROVAL_APPROVED]
    )
    owner = _owner_for(run.workspace)

    def _raise_broker_error(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(tasks_module.process_delivery_task, "delay", _raise_broker_error)

    decide_approval(
        workspace=run.workspace,
        approval_request=approval,
        actor=owner,
        actor_role=WorkspaceRole.OWNER,
        decision=ApprovalDecisionValue.APPROVE,
    )

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.APPROVED
    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_APPROVED
    )
    webhook_delivery = WebhookDelivery.objects.get(event=event)
    delivery = webhook_delivery.delivery
    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempt_count == 0
    assert not DeliveryAttempt.objects.filter(delivery=delivery).exists()

    # Still fully recoverable — nothing about the broker failure corrupted
    # or blocked the delivery's own state.
    from notifications.services import claim_delivery

    claimed, _token = claim_delivery(delivery_id=delivery.id)
    assert claimed.status == DeliveryStatus.CLAIMED


# ---------------------------------------------------------------------------
# Real approval-lifecycle rollback (section 8)
# ---------------------------------------------------------------------------


def test_approval_transaction_rollback_also_rolls_back_event_and_delivery(monkeypatch):
    """Forces the real ``decide_approval()`` transaction to fail *after*
    ``emit_event`` has already run but before that transaction commits —
    proves ``WebhookEvent``/``WebhookDelivery`` participate in the same
    atomic block rather than surviving the domain transaction's own
    rollback."""
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    WebhookEndpointFactory(
        workspace=run.workspace, subscribed_event_types=[WebhookEventType.APPROVAL_REJECTED]
    )
    owner = _owner_for(run.workspace)

    class Boom(Exception):
        pass

    def _explode(*args, **kwargs):
        raise Boom("simulated failure after emit_event, before commit")

    # ``_terminate_execution`` is the next thing decide_approval calls
    # after emit_event on a REJECT decision, and is not wrapped in any
    # try/except there — an exception here propagates straight out of the
    # whole transaction.atomic() block.
    monkeypatch.setattr("approvals.services._terminate_execution", _explode)

    with pytest.raises(Boom):
        decide_approval(
            workspace=run.workspace,
            approval_request=approval,
            actor=owner,
            actor_role=WorkspaceRole.OWNER,
            decision=ApprovalDecisionValue.REJECT,
        )

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.PENDING
    assert not WebhookEvent.objects.filter(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_REJECTED
    ).exists()
    assert not WebhookDelivery.objects.filter(workspace=run.workspace).exists()


# ---------------------------------------------------------------------------
# Handoff integration check (section 9)
# ---------------------------------------------------------------------------


def test_handoff_created_commits_state_event_and_delivery_together(monkeypatch):
    """``handoff.created`` uses the identical shared primitive
    (``emit_event`` inside an ``@transaction.atomic`` service function) —
    one focused commit-path assertion; rollback is already proven generically
    by ``test_emit_event_rolls_back_with_its_calling_transaction`` above."""
    from conversations.tests.factories import ConversationFactory
    from tickets.services import create_or_reuse_handoff

    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    conversation = ConversationFactory()
    WebhookEndpointFactory(
        workspace=conversation.workspace, subscribed_event_types=[WebhookEventType.HANDOFF_CREATED]
    )

    handoff, created = create_or_reuse_handoff(
        workspace=conversation.workspace,
        conversation=conversation,
        reason_code="low_confidence",
        safe_summary="test summary",
    )
    assert created is True

    event = WebhookEvent.objects.get(
        workspace=conversation.workspace, event_type=WebhookEventType.HANDOFF_CREATED
    )
    webhook_delivery = WebhookDelivery.objects.get(event=event)
    assert webhook_delivery.delivery.status == DeliveryStatus.PENDING
    assert event.payload_snapshot["handoff_id"] == str(handoff.id)


# ---------------------------------------------------------------------------
# Fanout atomicity (section 10)
# ---------------------------------------------------------------------------


def test_fanout_across_multiple_endpoints_is_atomic_with_its_transaction(monkeypatch):
    """One WebhookEvent, multiple WebhookDelivery rows — created as one
    coherent operation. A failure partway through fanout must not leave a
    partial distribution behind when the surrounding transaction rolls
    back."""
    workspace = WorkspaceFactory()
    WebhookEndpointFactory(
        workspace=workspace, subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED]
    )
    WebhookEndpointFactory(
        workspace=workspace, subscribed_event_types=[WebhookEventType.APPROVAL_REQUESTED]
    )

    from notifications.services import create_delivery as real_create_delivery

    call_count = {"n": 0}

    def flaky_create_delivery(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated mid-fanout failure")
        return real_create_delivery(**kwargs)

    monkeypatch.setattr("webhooks.services.create_delivery", flaky_create_delivery)

    with pytest.raises(RuntimeError):
        emit_event(
            workspace=workspace, event_type=WebhookEventType.APPROVAL_REQUESTED, data={"x": 1}
        )

    assert not WebhookEvent.objects.filter(workspace=workspace).exists()
    assert not WebhookDelivery.objects.filter(workspace=workspace).exists()
    assert not Delivery.objects.filter(workspace=workspace).exists()
