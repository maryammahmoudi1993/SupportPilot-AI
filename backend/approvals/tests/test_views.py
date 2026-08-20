"""Approval API: RBAC, tenant isolation, and spoof-resistance tests
(section 76-79, 114-117, 141)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import pending_refund_approval


def _client(user=None) -> APIClient:
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace) -> str:
    return f"/api/v1/workspaces/{workspace.id}/approvals"


@pytest.mark.django_db(transaction=True)
class TestApprovalList:
    def test_anonymous_is_401(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        assert _client().get(f"{_base(run.workspace)}/").status_code == 401

    def test_any_member_can_list(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.VIEWER)
        response = _client(membership.user).get(f"{_base(run.workspace)}/")
        assert response.status_code == 200
        assert response.data["results"][0]["id"] == str(approval.id)

    def test_filter_by_status(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.VIEWER)
        response = _client(membership.user).get(f"{_base(run.workspace)}/?status=approved")
        assert response.status_code == 200
        assert response.data["results"] == []

    def test_response_never_includes_credentials(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.VIEWER)
        response = _client(membership.user).get(f"{_base(run.workspace)}/")
        assert "sk_test" not in str(response.data)


@pytest.mark.django_db(transaction=True)
class TestApprovalCrossTenant:
    def test_foreign_workspace_detail_is_404(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        other = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(other.user).get(f"{_base(other.workspace)}/{approval.id}/")
        assert response.status_code == 404

    def test_foreign_workspace_approve_is_404(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        other = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(other.user).post(f"{_base(other.workspace)}/{approval.id}/approve/")
        assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
class TestApprovalDecisionAPI:
    def test_owner_can_approve(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(f"{_base(run.workspace)}/{approval.id}/approve/")
        assert response.status_code == 200
        assert response.data["status"] == "approved"

    def test_insufficient_role_gets_403(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(
            workspace=run.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        response = _client(membership.user).post(f"{_base(run.workspace)}/{approval.id}/approve/")
        assert response.status_code == 403
        assert response.data["error"]["code"] == "approval_permission_denied"

    def test_client_cannot_supply_a_decision_field_body_is_ignored(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        # POST to the *reject* endpoint while trying to smuggle "decision":
        # "approve" in the body — the URL, not the body, is authoritative.
        response = _client(membership.user).post(
            f"{_base(run.workspace)}/{approval.id}/reject/",
            data={"decision": "approve", "comment": "trying to sneak an approve"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["status"] == "rejected"

    def test_client_cannot_supply_approved_by(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        other = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.ADMIN)
        response = _client(membership.user).post(
            f"{_base(run.workspace)}/{approval.id}/approve/",
            data={"approved_by": str(other.user.id), "comment": "spoof attempt"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["decision"]["decided_by"] == membership.user.id  # the real caller

    def test_reject_then_approve_is_a_conflict(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        first = _client(membership.user).post(f"{_base(run.workspace)}/{approval.id}/reject/")
        assert first.status_code == 200
        second = _client(membership.user).post(f"{_base(run.workspace)}/{approval.id}/approve/")
        assert second.status_code == 409
        assert second.data["error"]["code"] == "approval_already_resolved"

    def test_comment_is_bounded_length(self, monkeypatch):
        run, approval, fake = pending_refund_approval(monkeypatch)
        membership = WorkspaceMembershipFactory(workspace=run.workspace, role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(run.workspace)}/{approval.id}/approve/",
            data={"comment": "x" * 5000},
            format="json",
        )
        assert response.status_code == 400
