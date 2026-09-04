"""Cross-tenant IDOR and nested-IDOR matrix for the policies domain (Phase
15 checkpoint 3, Part A). ``PolicyVersion`` has no workspace FK of its own
(only via ``policy.workspace``) and ``PolicyRule`` is two hops removed (via
``policy_version.policy.workspace``) — the nested cases below are the
primary target. Policy version/rule reads require ``CanManagePolicies``
(owner/admin only), unlike the top-level ``Policy`` read which is open to
any member — both ceilings are exercised here."""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from common.tests.security_matrix import two_workspaces

from .factories import PolicyFactory, PolicyRuleFactory, PolicyVersionFactory

__all__ = ["two_workspaces"]


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


def _base(workspace_id) -> str:
    return f"/api/v1/workspaces/{workspace_id}/policies"


@pytest.mark.django_db
class TestPolicyCrossTenant:
    def test_foreign_workspace_policy_detail_is_404(self, two_workspaces):
        d = two_workspaces
        policy = PolicyFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(f"{_base(d['workspace_b'].id)}/{policy.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_workspace_policy_patch_is_404_and_unchanged(self, two_workspaces):
        d = two_workspaces
        policy = PolicyFactory(workspace=d["workspace_a"], name="Original")
        response = _client(d["b_owner"].user).patch(
            f"{_base(d['workspace_b'].id)}/{policy.id}/", {"name": "Hijacked"}, format="json"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        policy.refresh_from_db()
        assert policy.name == "Original"

    def test_foreign_workspace_activate_is_404_and_status_unchanged(self, two_workspaces):
        d = two_workspaces
        from policies.models import PolicyStatus

        policy = PolicyFactory(workspace=d["workspace_a"], status=PolicyStatus.DRAFT)
        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/{policy.id}/activate/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        policy.refresh_from_db()
        assert policy.status == PolicyStatus.DRAFT


@pytest.mark.django_db
class TestPolicyVersionNestedIDOR:
    def test_foreign_policy_id_plus_own_version_id_is_404(self, two_workspaces):
        """Workspace B's own policy_id in the URL, but a real version_id
        that belongs to a *different* (Workspace A) policy — proves the
        lookup requires both segments to agree, not just workspace."""
        d = two_workspaces
        policy_a = PolicyFactory(workspace=d["workspace_a"])
        version_a = PolicyVersionFactory(policy=policy_a)
        policy_b = PolicyFactory(workspace=d["workspace_b"])

        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/{policy_b.id}/versions/{version_a.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_publish_a_foreign_workspaces_version_is_404_and_not_published(self, two_workspaces):
        d = two_workspaces
        from policies.models import PolicyVersionStatus

        policy_a = PolicyFactory(workspace=d["workspace_a"])
        version_a = PolicyVersionFactory(policy=policy_a, status=PolicyVersionStatus.DRAFT)
        policy_b = PolicyFactory(workspace=d["workspace_b"])

        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/{policy_b.id}/versions/{version_a.id}/publish/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        version_a.refresh_from_db()
        assert version_a.status == PolicyVersionStatus.DRAFT

    def test_foreign_workspace_version_list_is_404(self, two_workspaces):
        d = two_workspaces
        policy = PolicyFactory(workspace=d["workspace_a"])
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/{policy.id}/versions/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestPolicyRuleNestedIDOR:
    def test_two_hop_foreign_rule_creation_is_404_and_no_rule_created(self, two_workspaces):
        """policy_version -> policy -> workspace is a two-hop chain;
        confirm a rule cannot be added to Workspace A's version through
        Workspace B's own (mismatched) policy_id in the URL."""
        d = two_workspaces
        policy_a = PolicyFactory(workspace=d["workspace_a"])
        version_a = PolicyVersionFactory(policy=policy_a)
        policy_b = PolicyFactory(workspace=d["workspace_b"])
        rule_count_before = version_a.rules.count()

        response = _client(d["b_owner"].user).post(
            f"{_base(d['workspace_b'].id)}/{policy_b.id}/versions/{version_a.id}/rules/",
            {"name": "smuggled-rule", "effect": "deny", "condition_config": {}},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert version_a.rules.count() == rule_count_before

    def test_foreign_workspace_rule_list_is_404(self, two_workspaces):
        d = two_workspaces
        policy = PolicyFactory(workspace=d["workspace_a"])
        version = PolicyVersionFactory(policy=policy)
        PolicyRuleFactory(policy_version=version)
        response = _client(d["b_owner"].user).get(
            f"{_base(d['workspace_b'].id)}/{policy.id}/versions/{version.id}/rules/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestPolicyRBAC:
    def test_support_agent_can_read_policy_but_not_versions(self, two_workspaces):
        """Top-level Policy read is member-only; version/rule reads
        require CanManagePolicies (owner/admin) — a stricter ceiling this
        app applies even to GET, unlike most others."""
        d = two_workspaces
        policy = PolicyFactory(workspace=d["workspace_a"])
        version = PolicyVersionFactory(policy=policy)

        ok = _client(d["a_agent"].user).get(f"{_base(d['workspace_a'].id)}/{policy.id}/")
        assert ok.status_code == status.HTTP_200_OK

        denied = _client(d["a_agent"].user).get(
            f"{_base(d['workspace_a'].id)}/{policy.id}/versions/{version.id}/"
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_manage_policies_support_agent_cannot_create(self, two_workspaces):
        d = two_workspaces
        denied = _client(d["a_agent"].user).post(
            f"{_base(d['workspace_a'].id)}/", {"name": "New policy"}, format="json"
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        allowed = _client(d["a_admin"].user).post(
            f"{_base(d['workspace_a'].id)}/", {"name": "New policy"}, format="json"
        )
        assert allowed.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestPolicyMassAssignment:
    def test_client_cannot_set_policy_status_or_created_by_on_create(self, two_workspaces):
        d = two_workspaces
        response = _client(d["a_owner"].user).post(
            f"{_base(d['workspace_a'].id)}/",
            {
                "name": "New policy",
                "status": "active",
                "created_by": str(d["a_admin"].user.id),
                "workspace": str(d["workspace_b"].id),
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        from policies.models import Policy, PolicyStatus

        policy = Policy.objects.get(pk=response.data["id"])
        assert policy.status == PolicyStatus.DRAFT
        assert policy.workspace_id == d["workspace_a"].id
        assert policy.created_by_id == d["a_owner"].user.id
