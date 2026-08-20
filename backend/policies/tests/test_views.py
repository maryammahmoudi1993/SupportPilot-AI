"""Policy management API: RBAC and tenant isolation (section 74-75, 79-81,
114, 117)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import PolicyFactory, PolicyVersionFactory


def _client(user=None) -> APIClient:
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _base(workspace) -> str:
    return f"/api/v1/workspaces/{workspace.id}/policies"


@pytest.mark.django_db
class TestPolicyListCreate:
    def test_anonymous_is_401(self):
        membership = WorkspaceMembershipFactory()
        assert _client().get(f"{_base(membership.workspace)}/").status_code == 401

    def test_any_member_can_list(self):
        policy = PolicyFactory()
        membership = WorkspaceMembershipFactory(
            workspace=policy.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).get(f"{_base(membership.workspace)}/")
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "role,allowed",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, False),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_create_requires_owner_or_admin(self, role, allowed):
        membership = WorkspaceMembershipFactory(role=role)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/", data={"name": "Refund policy"}, format="json"
        )
        assert (response.status_code == 201) is allowed

    def test_client_cannot_set_status_or_created_by_through_create(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/",
            data={"name": "Refund policy", "status": "active", "created_by": "spoofed"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["status"] == "draft"  # server-derived, ignores client input


@pytest.mark.django_db
class TestPolicyCrossTenant:
    def test_foreign_workspace_policy_is_404(self):
        policy = PolicyFactory()
        other_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(other_membership.user).get(
            f"{_base(other_membership.workspace)}/{policy.id}/"
        )
        assert response.status_code == 404

    def test_foreign_workspace_activate_is_404(self):
        policy = PolicyFactory()
        other_membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(other_membership.user).post(
            f"{_base(other_membership.workspace)}/{policy.id}/activate/"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestPolicyRuleAPI:
    def test_unknown_predicate_is_rejected_with_400(self):
        version = PolicyVersionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=version.policy.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/rules/",
            data={
                "name": "bad",
                "priority": 0,
                "effect": "allow",
                "condition_config": {"all": [{"predicate": "nonexistent"}]},
            },
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "validation_error"

    def test_valid_rule_created_by_owner(self):
        version = PolicyVersionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=version.policy.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/rules/",
            data={
                "name": "allow-lookups",
                "priority": 0,
                "effect": "allow",
                "tool_key": "customer.lookup",
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["tool_key"] == "customer.lookup"

    def test_support_agent_cannot_add_rules(self):
        version = PolicyVersionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=version.policy.workspace, role=WorkspaceRole.SUPPORT_AGENT
        )
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/rules/",
            data={"name": "allow-lookups", "priority": 0, "effect": "allow"},
            format="json",
        )
        assert response.status_code == 403

    def test_list_rules(self):
        version = PolicyVersionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=version.policy.workspace, role=WorkspaceRole.OWNER
        )
        _client(membership.user).post(
            f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/rules/",
            data={"name": "r1", "priority": 0, "effect": "allow"},
            format="json",
        )
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/rules/"
        )
        assert response.status_code == 200
        assert len(response.data) == 1


@pytest.mark.django_db
class TestPolicyUpdate:
    def test_owner_can_update_name_and_description(self):
        policy = PolicyFactory()
        membership = WorkspaceMembershipFactory(
            workspace=policy.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).patch(
            f"{_base(membership.workspace)}/{policy.id}/",
            data={"name": "New name", "description": "New description"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["name"] == "New name"

    def test_viewer_cannot_update(self):
        policy = PolicyFactory()
        membership = WorkspaceMembershipFactory(
            workspace=policy.workspace, role=WorkspaceRole.VIEWER
        )
        response = _client(membership.user).patch(
            f"{_base(membership.workspace)}/{policy.id}/", data={"name": "x"}, format="json"
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestPolicyDeactivate:
    def test_owner_can_deactivate(self):
        from policies.models import PolicyStatus

        policy = PolicyFactory(status=PolicyStatus.ACTIVE)
        membership = WorkspaceMembershipFactory(
            workspace=policy.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/{policy.id}/deactivate/"
        )
        assert response.status_code == 200
        assert response.data["status"] == "inactive"


@pytest.mark.django_db
class TestPolicyVersionAPI:
    def test_create_and_list_versions(self):
        policy = PolicyFactory()
        membership = WorkspaceMembershipFactory(
            workspace=policy.workspace, role=WorkspaceRole.OWNER
        )
        create = _client(membership.user).post(
            f"{_base(membership.workspace)}/{policy.id}/versions/"
        )
        assert create.status_code == 201
        listed = _client(membership.user).get(
            f"{_base(membership.workspace)}/{policy.id}/versions/"
        )
        assert listed.status_code == 200
        assert len(listed.data) == 1

    def test_version_detail_includes_rules(self):
        version = PolicyVersionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=version.policy.workspace, role=WorkspaceRole.OWNER
        )
        _client(membership.user).post(
            f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/rules/",
            data={"name": "r1", "priority": 0, "effect": "allow"},
            format="json",
        )
        response = _client(membership.user).get(
            f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/"
        )
        assert response.status_code == 200
        assert len(response.data["rules"]) == 1

    def test_publish_version_activates_it(self):
        version = PolicyVersionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=version.policy.workspace, role=WorkspaceRole.OWNER
        )
        response = _client(membership.user).post(
            f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/publish/"
        )
        assert response.status_code == 200
        assert response.data["status"] == "active"

    def test_publish_already_active_version_is_400(self):
        version = PolicyVersionFactory()
        membership = WorkspaceMembershipFactory(
            workspace=version.policy.workspace, role=WorkspaceRole.OWNER
        )
        base = f"{_base(membership.workspace)}/{version.policy_id}/versions/{version.id}/publish/"
        _client(membership.user).post(base)
        response = _client(membership.user).post(base)
        assert response.status_code == 400

    def test_foreign_workspace_version_is_404(self):
        version = PolicyVersionFactory()
        other = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(other.user).get(
            f"{_base(other.workspace)}/{version.policy_id}/versions/{version.id}/"
        )
        assert response.status_code == 404
