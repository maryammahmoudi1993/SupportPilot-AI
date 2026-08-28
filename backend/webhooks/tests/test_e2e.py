"""Phase 10 Block 5 — full end-to-end webhook flows through real domain
services (never bypassed by manually creating only the event), a real
signed HTTP attempt against a fake pinned transport, and — for the retry
scenario — the real recovery sweeper rather than manually advancing state.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from accounts.tests.factories import UserFactory
from approvals.models import ApprovalDecisionValue, ApprovalStatus
from approvals.services import decide_approval
from approvals.tests.factories import pending_refund_approval
from notifications.models import Delivery, DeliveryStatus
from notifications.recovery import dispatch_due_deliveries
from notifications.tasks import process_delivery_task
from webhooks.models import WebhookDelivery, WebhookEvent, WebhookEventType
from webhooks.tests.factories import WebhookEndpointFactory
from webhooks.transport import TransportResult
from workspaces.models import WorkspaceMembership, WorkspaceRole

pytestmark = pytest.mark.django_db(transaction=True)


def _owner_for(workspace):
    user = UserFactory()
    WorkspaceMembership.objects.create(
        workspace=workspace, user=user, role=WorkspaceRole.OWNER, is_active=True
    )
    return user


def _fake_transport(status=204):
    calls: list[dict] = []

    def fake(*, scheme, ip, port, hostname, path_and_query, headers, body, method="POST"):
        calls.append({"headers": headers, "body": body})
        return TransportResult(status_code=status, latency_ms=1)

    return fake, calls


def test_approval_decision_to_signed_204_end_to_end(monkeypatch):
    """Real approval decision (never a manually-constructed event) ->
    transactionally durable WebhookEvent/WebhookDelivery -> real signed
    HTTP attempt -> DELIVERED."""
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    WebhookEndpointFactory(
        workspace=run.workspace, subscribed_event_types=[WebhookEventType.APPROVAL_APPROVED]
    )
    owner = _owner_for(run.workspace)

    fake_transport, calls = _fake_transport(status=204)
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    decide_approval(
        workspace=run.workspace,
        approval_request=approval,
        actor=owner,
        actor_role=WorkspaceRole.OWNER,
        decision=ApprovalDecisionValue.APPROVE,
    )

    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_APPROVED
    )
    webhook_delivery = WebhookDelivery.objects.get(event=event)
    delivery_id = webhook_delivery.delivery_id

    result = process_delivery_task.apply(args=[str(delivery_id)]).get()
    assert result == "processed"

    delivery = Delivery.objects.get(pk=delivery_id)
    assert delivery.status == DeliveryStatus.DELIVERED
    assert len(calls) == 1
    assert calls[0]["headers"]["X-SupportPilot-Event-Id"] == str(event.id)
    assert "arguments" not in event.payload_snapshot


def test_handoff_creation_to_signed_204_end_to_end(monkeypatch):
    """Real handoff-creation service -> handoff.created event -> real
    signed HTTP attempt -> DELIVERED, with handoff business state and
    delivery state independently correct."""
    from conversations.tests.factories import ConversationFactory
    from tickets.services import create_or_reuse_handoff

    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    conversation = ConversationFactory()
    WebhookEndpointFactory(
        workspace=conversation.workspace, subscribed_event_types=[WebhookEventType.HANDOFF_CREATED]
    )
    fake_transport, calls = _fake_transport(status=204)
    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    handoff, created = create_or_reuse_handoff(
        workspace=conversation.workspace,
        conversation=conversation,
        reason_code="low_confidence",
        safe_summary="Customer needs a human.",
    )
    assert created is True

    event = WebhookEvent.objects.get(
        workspace=conversation.workspace, event_type=WebhookEventType.HANDOFF_CREATED
    )
    webhook_delivery = WebhookDelivery.objects.get(event=event)

    result = process_delivery_task.apply(args=[str(webhook_delivery.delivery_id)]).get()
    assert result == "processed"

    delivery = Delivery.objects.get(pk=webhook_delivery.delivery_id)
    assert delivery.status == DeliveryStatus.DELIVERED
    assert len(calls) == 1

    # The handoff's own business state is independent of delivery outcome.
    handoff.refresh_from_db()
    assert handoff.reason_code == "low_confidence"


def test_webhook_500_then_recovery_sweep_then_204_end_to_end(monkeypatch, settings):
    """Domain event -> HTTP 500 -> RETRY_SCHEDULED -> sweeper before due
    (no send) -> due time advances -> sweeper publishes -> HTTP 204 ->
    DELIVERED, driven entirely through ``dispatch_due_deliveries`` (the
    real recovery dispatcher), never by manually calling
    ``handle_webhook_delivery_attempt`` directly."""
    settings.DELIVERY_RETRY_BASE_DELAY_SECONDS = 30
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    WebhookEndpointFactory(
        workspace=run.workspace, subscribed_event_types=[WebhookEventType.APPROVAL_APPROVED]
    )
    owner = _owner_for(run.workspace)

    responses = iter([500, 204])

    def fake_transport(*, scheme, ip, port, hostname, path_and_query, headers, body, method="POST"):
        return TransportResult(status_code=next(responses), latency_ms=1)

    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    def _synchronous_dispatch(delivery_id):
        process_delivery_task.apply(args=[delivery_id]).get()

    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing", _synchronous_dispatch
    )

    decide_approval(
        workspace=run.workspace,
        approval_request=approval,
        actor=owner,
        actor_role=WorkspaceRole.OWNER,
        decision=ApprovalDecisionValue.APPROVE,
    )
    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_APPROVED
    )
    delivery_id = WebhookDelivery.objects.get(event=event).delivery_id

    # First sweep: the initial on_commit publication (unpatched, real
    # ``.delay()``) only published a Celery message nobody in this test
    # process ever consumes — this sweep is what actually makes the first
    # real attempt, using the patched synchronous dispatch above; it gets
    # the 500 and schedules a retry.
    dispatch_due_deliveries()
    delivery = Delivery.objects.get(pk=delivery_id)
    assert delivery.status == DeliveryStatus.RETRY_SCHEDULED

    # Before due: a sweep must not dispatch it again.
    dispatch_due_deliveries()
    delivery.refresh_from_db()
    assert delivery.attempt_count == 1  # unchanged — no early second attempt

    # Time advances to due; the next sweep publishes and this attempt
    # succeeds.
    Delivery.objects.filter(pk=delivery_id).update(next_attempt_at=timezone.now())
    dispatch_due_deliveries()

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.DELIVERED
    assert delivery.attempt_count == 2


def test_fanout_delivers_independently_across_two_endpoints(monkeypatch, settings):
    """Section 63: one domain event, two ACTIVE subscribed endpoints ->
    two independent ``WebhookDelivery``/``Delivery`` rows. Endpoint A
    succeeds immediately; endpoint B fails once and retries. B's retry
    must never affect A's already-DELIVERED state, and the approval's own
    business state is unaffected by either outcome."""
    settings.DELIVERY_RETRY_BASE_DELAY_SECONDS = 30
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    run, approval, _fake = pending_refund_approval(monkeypatch)
    endpoint_a = WebhookEndpointFactory(
        workspace=run.workspace, subscribed_event_types=[WebhookEventType.APPROVAL_APPROVED]
    )
    endpoint_b = WebhookEndpointFactory(
        workspace=run.workspace, subscribed_event_types=[WebhookEventType.APPROVAL_APPROVED]
    )
    owner = _owner_for(run.workspace)

    b_responses = iter([500, 204])

    def fake_transport(*, scheme, ip, port, hostname, path_and_query, headers, body, method="POST"):
        delivery_id = headers["X-SupportPilot-Delivery-Id"]
        target = WebhookDelivery.objects.get(delivery_id=delivery_id).endpoint_id
        if target == endpoint_a.id:
            return TransportResult(status_code=204, latency_ms=1)
        return TransportResult(status_code=next(b_responses), latency_ms=1)

    monkeypatch.setattr("webhooks.services.send_pinned_request", fake_transport)

    def _synchronous_dispatch(delivery_id):
        process_delivery_task.apply(args=[delivery_id]).get()

    monkeypatch.setattr(
        "notifications.recovery.dispatch_delivery_for_processing", _synchronous_dispatch
    )

    decide_approval(
        workspace=run.workspace,
        approval_request=approval,
        actor=owner,
        actor_role=WorkspaceRole.OWNER,
        decision=ApprovalDecisionValue.APPROVE,
    )
    event = WebhookEvent.objects.get(
        workspace=run.workspace, event_type=WebhookEventType.APPROVAL_APPROVED
    )
    assert WebhookDelivery.objects.filter(event=event).count() == 2
    delivery_a_id = WebhookDelivery.objects.get(event=event, endpoint=endpoint_a).delivery_id
    delivery_b_id = WebhookDelivery.objects.get(event=event, endpoint=endpoint_b).delivery_id
    assert delivery_a_id != delivery_b_id

    dispatch_due_deliveries()  # A -> DELIVERED, B -> RETRY_SCHEDULED (500)
    delivery_a = Delivery.objects.get(pk=delivery_a_id)
    delivery_b = Delivery.objects.get(pk=delivery_b_id)
    assert delivery_a.status == DeliveryStatus.DELIVERED
    assert delivery_b.status == DeliveryStatus.RETRY_SCHEDULED

    # B's retry proceeds independently and never touches A.
    Delivery.objects.filter(pk=delivery_b_id).update(next_attempt_at=timezone.now())
    dispatch_due_deliveries()
    delivery_a.refresh_from_db()
    delivery_b.refresh_from_db()
    assert delivery_a.status == DeliveryStatus.DELIVERED
    assert delivery_a.attempt_count == 1  # untouched by B's second attempt
    assert delivery_b.status == DeliveryStatus.DELIVERED

    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.APPROVED
