"""Human handoff: model invariants, service idempotency/RBAC, selectors, and
the API surface (Phase 9, section 44-53)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient

from agents.tests.factories import AgentRunFactory
from conversations.tests.factories import ConversationFactory
from tickets import selectors, services
from tickets.models import HumanHandoffReason, HumanHandoffStatus
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceFactory, WorkspaceMembershipFactory

from .factories import HumanHandoffFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestHumanHandoffModel:
    def test_at_most_one_active_handoff_per_conversation(self):
        conversation = ConversationFactory()
        HumanHandoffFactory(workspace=conversation.workspace, conversation=conversation)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                HumanHandoffFactory(workspace=conversation.workspace, conversation=conversation)

    def test_a_resolved_handoff_does_not_block_a_new_one(self):
        conversation = ConversationFactory()
        first = HumanHandoffFactory(workspace=conversation.workspace, conversation=conversation)
        first.status = HumanHandoffStatus.RESOLVED
        first.save()
        second = HumanHandoffFactory(workspace=conversation.workspace, conversation=conversation)
        assert second.pk != first.pk

    def test_cross_workspace_conversation_is_rejected(self):
        handoff = HumanHandoffFactory.build(
            workspace=WorkspaceFactory(), conversation=ConversationFactory()
        )
        with pytest.raises(DjangoValidationError):
            handoff.full_clean()


@pytest.mark.django_db
class TestCreateOrReuseHandoff:
    def test_creates_a_pending_handoff_and_records_audit(self):
        from audit.models import AuditAction, AuditEvent

        conversation = ConversationFactory()
        handoff, created = services.create_or_reuse_handoff(
            workspace=conversation.workspace,
            conversation=conversation,
            reason_code=HumanHandoffReason.CUSTOMER_REQUESTED,
            safe_summary="Customer asked for a human.",
        )
        assert created is True
        assert handoff.status == HumanHandoffStatus.PENDING
        assert AuditEvent.objects.filter(
            action=AuditAction.HUMAN_HANDOFF_CREATED, target_id=str(handoff.id)
        ).exists()

    def test_reuses_the_existing_active_handoff_idempotently(self):
        conversation = ConversationFactory()
        first, first_created = services.create_or_reuse_handoff(
            workspace=conversation.workspace,
            conversation=conversation,
            reason_code=HumanHandoffReason.CUSTOMER_REQUESTED,
            safe_summary="First trigger.",
        )
        second, second_created = services.create_or_reuse_handoff(
            workspace=conversation.workspace,
            conversation=conversation,
            reason_code=HumanHandoffReason.RUNTIME_FAILURE,
            safe_summary="Second trigger — should be a no-op.",
        )
        assert first_created is True
        assert second_created is False
        assert second.id == first.id
        assert second.safe_summary == "First trigger."

    def test_foreign_conversation_is_rejected(self):
        workspace = WorkspaceFactory()
        foreign_conversation = ConversationFactory(workspace=WorkspaceFactory())
        with pytest.raises(DRFValidationError):
            services.create_or_reuse_handoff(
                workspace=workspace,
                conversation=foreign_conversation,
                reason_code=HumanHandoffReason.CUSTOMER_REQUESTED,
                safe_summary="x",
            )


@pytest.mark.django_db
class TestAssignAndResolveHandoff:
    def test_manager_can_assign_and_resolve(self):
        handoff = HumanHandoffFactory()
        manager = WorkspaceMembershipFactory(
            workspace=handoff.workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        assigned = services.assign_handoff(
            workspace=handoff.workspace,
            actor=manager.user,
            actor_membership=manager,
            handoff=handoff,
        )
        assert assigned.status == HumanHandoffStatus.ASSIGNED
        assert assigned.assigned_to_id == manager.id

        resolved = services.resolve_handoff(
            workspace=handoff.workspace,
            actor=manager.user,
            actor_membership=manager,
            handoff=assigned,
        )
        assert resolved.status == HumanHandoffStatus.RESOLVED
        assert resolved.resolved_at is not None

    def test_support_agent_cannot_assign(self):
        handoff = HumanHandoffFactory()
        agent = WorkspaceMembershipFactory(
            workspace=handoff.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        with pytest.raises(PermissionDenied):
            services.assign_handoff(
                workspace=handoff.workspace,
                actor=agent.user,
                actor_membership=agent,
                handoff=handoff,
            )

    def test_resolving_an_already_resolved_handoff_is_rejected(self):
        handoff = HumanHandoffFactory(status=HumanHandoffStatus.RESOLVED)
        manager = WorkspaceMembershipFactory(
            workspace=handoff.workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        with pytest.raises(DRFValidationError):
            services.resolve_handoff(
                workspace=handoff.workspace,
                actor=manager.user,
                actor_membership=manager,
                handoff=handoff,
            )


@pytest.mark.django_db
class TestCancelHandoffsForRun:
    def test_cancels_active_handoffs_for_a_run_and_records_audit(self):
        from audit.models import AuditAction, AuditEvent

        run = AgentRunFactory()
        handoff = HumanHandoffFactory(workspace=run.workspace, agent_run=run)
        services.cancel_handoffs_for_run(agent_run=run)
        handoff.refresh_from_db()
        assert handoff.status == HumanHandoffStatus.CANCELLED
        assert AuditEvent.objects.filter(
            action=AuditAction.HUMAN_HANDOFF_CANCELLED, target_id=str(handoff.id)
        ).exists()

    def test_is_a_no_op_when_the_run_has_no_handoff(self):
        run = AgentRunFactory()
        services.cancel_handoffs_for_run(agent_run=run)  # must not raise


@pytest.mark.django_db
class TestHandoffSelectors:
    def test_get_for_workspace_or_404_rejects_foreign_workspace(self):
        from django.http import Http404

        handoff = HumanHandoffFactory()
        with pytest.raises(Http404):
            selectors.handoff_get_for_workspace_or_404(
                workspace=WorkspaceFactory(), handoff_id=handoff.id
            )

    def test_list_filters_by_status_and_conversation(self):
        conversation = ConversationFactory()
        pending = HumanHandoffFactory(workspace=conversation.workspace, conversation=conversation)
        HumanHandoffFactory(workspace=conversation.workspace, status=HumanHandoffStatus.RESOLVED)

        results = list(
            selectors.handoff_list_for_workspace(
                workspace=conversation.workspace, status=HumanHandoffStatus.PENDING
            )
        )
        assert results == [pending]


@pytest.mark.django_db
class TestHumanHandoffApi:
    def test_requires_authentication(self):
        workspace = WorkspaceFactory()
        response = _client().get(f"/api/v1/workspaces/{workspace.id}/handoffs/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_member_can_list_and_view(self):
        handoff = HumanHandoffFactory()
        membership = WorkspaceMembershipFactory(
            workspace=handoff.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{handoff.workspace_id}/handoffs/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(handoff.id)

        detail = _client(membership.user).get(
            f"/api/v1/workspaces/{handoff.workspace_id}/handoffs/{handoff.id}/"
        )
        assert detail.status_code == status.HTTP_200_OK

    def test_foreign_workspace_handoff_id_404s(self):
        handoff = HumanHandoffFactory()
        other_workspace = WorkspaceFactory()
        membership = WorkspaceMembershipFactory(workspace=other_workspace, role=WorkspaceRole.OWNER)
        response = _client(membership.user).get(
            f"/api/v1/workspaces/{other_workspace.id}/handoffs/{handoff.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_support_agent_cannot_assign_or_resolve(self):
        handoff = HumanHandoffFactory()
        membership = WorkspaceMembershipFactory(
            workspace=handoff.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        assign_response = _client(membership.user).post(
            f"/api/v1/workspaces/{handoff.workspace_id}/handoffs/{handoff.id}/assign/",
            {},
            format="json",
        )
        assert assign_response.status_code == status.HTTP_403_FORBIDDEN

    def test_manager_can_self_assign_then_resolve(self):
        handoff = HumanHandoffFactory()
        membership = WorkspaceMembershipFactory(
            workspace=handoff.workspace, role=WorkspaceRole.SUPPORT_MANAGER
        )
        assign_response = _client(membership.user).post(
            f"/api/v1/workspaces/{handoff.workspace_id}/handoffs/{handoff.id}/assign/",
            {},
            format="json",
        )
        assert assign_response.status_code == status.HTTP_200_OK
        assert assign_response.data["status"] == HumanHandoffStatus.ASSIGNED

        resolve_response = _client(membership.user).post(
            f"/api/v1/workspaces/{handoff.workspace_id}/handoffs/{handoff.id}/resolve/",
            {},
            format="json",
        )
        assert resolve_response.status_code == status.HTTP_200_OK
        assert resolve_response.data["status"] == HumanHandoffStatus.RESOLVED
