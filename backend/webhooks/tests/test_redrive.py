"""Manual webhook delivery redrive (Phase 10 Block 4, section 28-37):
service-level state/security semantics plus the RBAC/tenant-isolation API
surface, mirroring the conventions already established in ``test_views.py``.
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from audit.models import AuditAction, AuditEvent
from notifications.models import (
    AttemptStatus,
    Delivery,
    DeliveryAttempt,
    DeliveryChannel,
    DeliveryStatus,
)
from notifications.services import (
    claim_delivery,
    complete_delivery_failure,
    complete_delivery_success,
    create_delivery,
)
from webhooks.errors import WebhookDeliveryNotRedrivableError, WebhookEndpointDisabledError
from webhooks.models import WebhookDelivery, WebhookEndpointStatus
from webhooks.services import handle_webhook_delivery_attempt, redrive_webhook_delivery
from webhooks.tests.factories import WebhookEndpointFactory, WebhookEventFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

pytestmark = pytest.mark.django_db


def _client(user=None) -> APIClient:
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace) -> str:
    return f"/api/v1/workspaces/{workspace.id}/webhooks"


def _exhausted_delivery(
    monkeypatch, *, endpoint=None, max_attempts=1, terminal_status=DeliveryStatus.FAILED
):
    endpoint = endpoint or WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    delivery = create_delivery(
        workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK, max_attempts=max_attempts
    )
    webhook_delivery = WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    claimed, token = claim_delivery(delivery_id=delivery.id)
    if terminal_status == DeliveryStatus.DEAD:
        complete_delivery_failure(
            delivery_id=claimed.id,
            claim_token=token,
            safe_error_code="webhook_http_400",
            retryable=False,
        )
    else:
        complete_delivery_failure(
            delivery_id=claimed.id,
            claim_token=token,
            safe_error_code="webhook_http_500",
            retryable=True,
        )
    delivery.refresh_from_db()
    assert delivery.status == terminal_status
    return webhook_delivery


# ---------------------------------------------------------------------------
# Service-level state semantics (section 30-31, 35-37)
# ---------------------------------------------------------------------------


class TestRedriveServiceState:
    def test_redrive_from_failed_reopens_with_extended_attempt_budget(self, monkeypatch, settings):
        settings.WEBHOOKS_REDRIVE_ATTEMPT_ALLOWANCE = 3
        webhook_delivery = _exhausted_delivery(monkeypatch, terminal_status=DeliveryStatus.FAILED)
        original_max_attempts = webhook_delivery.delivery.max_attempts

        redrive_webhook_delivery(
            workspace=webhook_delivery.workspace, webhook_delivery=webhook_delivery, actor=None
        )

        delivery = Delivery.objects.get(pk=webhook_delivery.delivery_id)
        assert delivery.status == DeliveryStatus.PENDING
        assert delivery.max_attempts == original_max_attempts + 3
        assert delivery.failed_at is None
        # Same logical row/event/delivery — never a second one (section 30).
        assert WebhookDelivery.objects.filter(event_id=webhook_delivery.event_id).count() == 1

    def test_redrive_from_dead_reopens_too(self, monkeypatch):
        webhook_delivery = _exhausted_delivery(monkeypatch, terminal_status=DeliveryStatus.DEAD)

        redrive_webhook_delivery(
            workspace=webhook_delivery.workspace, webhook_delivery=webhook_delivery, actor=None
        )

        delivery = Delivery.objects.get(pk=webhook_delivery.delivery_id)
        assert delivery.status == DeliveryStatus.PENDING

    def test_redrive_preserves_attempt_history_and_continues_numbering(self, monkeypatch):
        """Section 31: historical DeliveryAttempt rows are never rewritten,
        and the next attempt after redrive continues monotonically (e.g.
        attempt 2, not a reset back to attempt 1)."""
        webhook_delivery = _exhausted_delivery(monkeypatch, max_attempts=1)
        delivery_id = webhook_delivery.delivery_id
        original_attempt = DeliveryAttempt.objects.get(delivery_id=delivery_id, attempt_number=1)

        redrive_webhook_delivery(
            workspace=webhook_delivery.workspace, webhook_delivery=webhook_delivery, actor=None
        )

        # The original attempt row is untouched.
        original_attempt.refresh_from_db()
        assert original_attempt.status == AttemptStatus.FAILED
        assert original_attempt.attempt_number == 1

        # The next claim continues at attempt 2, never resets to 1.
        claimed, token = claim_delivery(delivery_id=delivery_id)
        assert claimed.attempt_count == 2
        assert DeliveryAttempt.objects.filter(delivery_id=delivery_id).count() == 2
        assert (
            not DeliveryAttempt.objects.filter(delivery_id=delivery_id, attempt_number=1)
            .exclude(pk=original_attempt.pk)
            .exists()
        )

    def test_redrive_rejects_pending_delivery(self, monkeypatch):
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        webhook_delivery = WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        with pytest.raises(WebhookDeliveryNotRedrivableError):
            redrive_webhook_delivery(
                workspace=endpoint.workspace, webhook_delivery=webhook_delivery, actor=None
            )

    def test_redrive_rejects_actively_claimed_delivery(self, monkeypatch):
        """Section 35: an active, unexpired claim must never be reset out
        from underneath the worker holding it."""
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        webhook_delivery = WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        claim_delivery(delivery_id=delivery.id)

        with pytest.raises(WebhookDeliveryNotRedrivableError):
            redrive_webhook_delivery(
                workspace=endpoint.workspace, webhook_delivery=webhook_delivery, actor=None
            )
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.CLAIMED

    def test_redrive_rejects_already_delivered(self, monkeypatch):
        """Section 36: never duplicates an already-confirmed external success."""
        endpoint = WebhookEndpointFactory()
        event = WebhookEventFactory(workspace=endpoint.workspace)
        delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
        webhook_delivery = WebhookDelivery.objects.create(
            delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
        )
        claimed, token = claim_delivery(delivery_id=delivery.id)
        complete_delivery_success(delivery_id=claimed.id, claim_token=token)

        with pytest.raises(WebhookDeliveryNotRedrivableError):
            redrive_webhook_delivery(
                workspace=endpoint.workspace, webhook_delivery=webhook_delivery, actor=None
            )
        delivery.refresh_from_db()
        assert delivery.status == DeliveryStatus.DELIVERED

    def test_redrive_rejects_disabled_endpoint_without_any_state_change(self, monkeypatch):
        """Section 37: rejected before any delivery-state mutation — no
        network call is ever produced from redrive against a disabled
        endpoint."""
        webhook_delivery = _exhausted_delivery(monkeypatch)
        webhook_delivery.endpoint.status = WebhookEndpointStatus.DISABLED
        webhook_delivery.endpoint.save(update_fields=["status"])
        original_max_attempts = webhook_delivery.delivery.max_attempts

        with pytest.raises(WebhookEndpointDisabledError):
            redrive_webhook_delivery(
                workspace=webhook_delivery.workspace, webhook_delivery=webhook_delivery, actor=None
            )

        delivery = Delivery.objects.get(pk=webhook_delivery.delivery_id)
        assert delivery.status == DeliveryStatus.FAILED
        assert delivery.max_attempts == original_max_attempts

    def test_redrive_still_re_validates_ssrf_on_the_next_actual_attempt(self, monkeypatch):
        """Section 32: redrive itself performs no network I/O — the *next*
        attempt independently re-resolves DNS/SSRF, so an endpoint that was
        valid at creation but now resolves privately is still blocked."""
        from webhooks.errors import WebhookDestinationBlockedError

        webhook_delivery = _exhausted_delivery(monkeypatch)
        redrive_webhook_delivery(
            workspace=webhook_delivery.workspace, webhook_delivery=webhook_delivery, actor=None
        )

        def _now_blocked(hostname, port):
            raise WebhookDestinationBlockedError()

        monkeypatch.setattr("webhooks.services.resolve_and_validate", _now_blocked)

        def _fail_if_called(**kwargs):
            raise AssertionError("transport must never be called for a now-blocked destination")

        monkeypatch.setattr("webhooks.services.send_pinned_request", _fail_if_called)

        claimed, token = claim_delivery(delivery_id=webhook_delivery.delivery_id)
        handle_webhook_delivery_attempt(delivery=claimed, claim_token=token)

        delivery = Delivery.objects.get(pk=webhook_delivery.delivery_id)
        assert delivery.status == DeliveryStatus.DEAD
        assert delivery.last_error_code == WebhookDestinationBlockedError.code

    def test_redrive_records_an_audit_event(self, monkeypatch):
        webhook_delivery = _exhausted_delivery(monkeypatch)
        redrive_webhook_delivery(
            workspace=webhook_delivery.workspace, webhook_delivery=webhook_delivery, actor=None
        )
        assert AuditEvent.objects.filter(
            action=AuditAction.WEBHOOK_DELIVERY_REDRIVEN,
            target_id=str(webhook_delivery.delivery_id),
        ).exists()


# ---------------------------------------------------------------------------
# API surface (section 29, 34)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,allowed",
    [
        (WorkspaceRole.OWNER, True),
        (WorkspaceRole.ADMIN, True),
        (WorkspaceRole.SUPPORT_MANAGER, True),
        (WorkspaceRole.SUPPORT_AGENT, False),
        (WorkspaceRole.VIEWER, False),
    ],
)
def test_redrive_requires_manager_or_above(monkeypatch, role, allowed):
    webhook_delivery = _exhausted_delivery(monkeypatch)
    membership = WorkspaceMembershipFactory(workspace=webhook_delivery.workspace, role=role)
    response = _client(membership.user).post(
        f"{_base(webhook_delivery.workspace)}/deliveries/{webhook_delivery.delivery_id}/redrive/"
    )
    assert (response.status_code == 200) is allowed


def test_redrive_get_is_not_allowed(monkeypatch):
    webhook_delivery = _exhausted_delivery(monkeypatch)
    membership = WorkspaceMembershipFactory(
        workspace=webhook_delivery.workspace, role=WorkspaceRole.OWNER
    )
    response = _client(membership.user).get(
        f"{_base(webhook_delivery.workspace)}/deliveries/{webhook_delivery.delivery_id}/redrive/"
    )
    assert response.status_code == 405


def test_redrive_returns_current_status(monkeypatch):
    webhook_delivery = _exhausted_delivery(monkeypatch)
    membership = WorkspaceMembershipFactory(
        workspace=webhook_delivery.workspace, role=WorkspaceRole.OWNER
    )
    response = _client(membership.user).post(
        f"{_base(webhook_delivery.workspace)}/deliveries/{webhook_delivery.delivery_id}/redrive/"
    )
    assert response.status_code == 200
    assert response.data["status"] == "pending"


def test_redrive_foreign_workspace_delivery_is_404(monkeypatch):
    webhook_delivery = _exhausted_delivery(monkeypatch)
    membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)  # different workspace
    response = _client(membership.user).post(
        f"{_base(membership.workspace)}/deliveries/{webhook_delivery.delivery_id}/redrive/"
    )
    assert response.status_code == 404


def test_redrive_nonexistent_delivery_is_404():
    membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
    response = _client(membership.user).post(
        f"{_base(membership.workspace)}/deliveries/{uuid.uuid4()}/redrive/"
    )
    assert response.status_code == 404


def test_redrive_role_demotion_after_token_issued_denies_mutation(monkeypatch):
    webhook_delivery = _exhausted_delivery(monkeypatch)
    membership = WorkspaceMembershipFactory(
        workspace=webhook_delivery.workspace, role=WorkspaceRole.SUPPORT_MANAGER
    )
    client = _client(membership.user)
    membership.role = WorkspaceRole.SUPPORT_AGENT
    membership.save(update_fields=["role"])

    response = client.post(
        f"{_base(webhook_delivery.workspace)}/deliveries/{webhook_delivery.delivery_id}/redrive/"
    )
    assert response.status_code == 403


def test_redrive_on_not_redrivable_state_returns_safe_400(monkeypatch):
    endpoint = WebhookEndpointFactory()
    event = WebhookEventFactory(workspace=endpoint.workspace)
    monkeypatch.setattr("webhooks.services.resolve_and_validate", lambda h, p: "93.184.216.34")
    delivery = create_delivery(workspace=endpoint.workspace, channel=DeliveryChannel.WEBHOOK)
    WebhookDelivery.objects.create(
        delivery=delivery, workspace=endpoint.workspace, endpoint=endpoint, event=event
    )
    membership = WorkspaceMembershipFactory(workspace=endpoint.workspace, role=WorkspaceRole.OWNER)

    response = _client(membership.user).post(
        f"{_base(endpoint.workspace)}/deliveries/{delivery.id}/redrive/"
    )
    assert response.status_code == 400
    assert response.data["error"]["code"] == "webhook_delivery_not_redrivable"
