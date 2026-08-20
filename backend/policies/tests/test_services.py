"""Policy configuration service tests (section 13-17, 80-81, 120)."""

from __future__ import annotations

import pytest

from accounts.tests.factories import UserFactory
from policies import services
from policies.errors import (
    PolicyInvalidRuleError,
    PolicyLimitExceededError,
    PolicyVersionNotActivatableError,
)
from policies.models import Policy, PolicyRule, PolicyStatus, PolicyVersionStatus
from workspaces.tests.factories import WorkspaceFactory


@pytest.mark.django_db
class TestPolicyLifecycle:
    def test_create_policy_defaults_to_draft(self):
        workspace = WorkspaceFactory()
        actor = UserFactory()
        policy = services.create_policy(workspace=workspace, actor=actor, name="  Refunds  ")
        assert policy.status == PolicyStatus.DRAFT
        assert policy.name == "Refunds"  # trimmed

    def test_activate_deactivates_previously_active_policy(self):
        workspace = WorkspaceFactory()
        actor = UserFactory()
        first = services.create_policy(workspace=workspace, actor=actor, name="First")
        second = services.create_policy(workspace=workspace, actor=actor, name="Second")
        services.activate_policy(workspace=workspace, policy=first, actor=actor)
        services.activate_policy(workspace=workspace, policy=second, actor=actor)
        first.refresh_from_db()
        assert first.status == PolicyStatus.INACTIVE
        assert Policy.objects.get(pk=second.pk).status == PolicyStatus.ACTIVE

    def test_publish_freezes_version_and_supersedes_previous_active(self):
        workspace = WorkspaceFactory()
        actor = UserFactory()
        policy = services.create_policy(workspace=workspace, actor=actor, name="Refunds")
        v1 = services.create_policy_version(workspace=workspace, policy=policy, actor=actor)
        services.publish_policy_version(workspace=workspace, policy_version=v1, actor=actor)
        v2 = services.create_policy_version(workspace=workspace, policy=policy, actor=actor)
        services.publish_policy_version(workspace=workspace, policy_version=v2, actor=actor)
        v1.refresh_from_db()
        assert v1.status == PolicyVersionStatus.SUPERSEDED
        assert v2.version == 2

    def test_publish_non_draft_version_is_rejected(self):
        workspace = WorkspaceFactory()
        actor = UserFactory()
        policy = services.create_policy(workspace=workspace, actor=actor, name="Refunds")
        version = services.create_policy_version(workspace=workspace, policy=policy, actor=actor)
        services.publish_policy_version(workspace=workspace, policy_version=version, actor=actor)
        with pytest.raises(PolicyVersionNotActivatableError):
            services.publish_policy_version(
                workspace=workspace, policy_version=version, actor=actor
            )

    def test_add_rule_rejects_unknown_predicate(self):
        workspace = WorkspaceFactory()
        actor = UserFactory()
        policy = services.create_policy(workspace=workspace, actor=actor, name="Refunds")
        version = services.create_policy_version(workspace=workspace, policy=policy, actor=actor)
        with pytest.raises(PolicyInvalidRuleError):
            services.add_policy_rule(
                workspace=workspace,
                policy_version=version,
                actor=actor,
                data={
                    "name": "bad",
                    "priority": 0,
                    "effect": "allow",
                    "condition_config": {"all": [{"predicate": "nonexistent"}]},
                },
            )

    def test_add_rule_rejects_once_version_is_published(self):
        workspace = WorkspaceFactory()
        actor = UserFactory()
        policy = services.create_policy(workspace=workspace, actor=actor, name="Refunds")
        version = services.create_policy_version(workspace=workspace, policy=policy, actor=actor)
        version = services.publish_policy_version(
            workspace=workspace, policy_version=version, actor=actor
        )
        with pytest.raises(PolicyInvalidRuleError):
            services.add_policy_rule(
                workspace=workspace,
                policy_version=version,
                actor=actor,
                data={"name": "late", "priority": 0, "effect": "allow"},
            )

    def test_add_rule_enforces_max_rule_count(self, monkeypatch):
        import policies.services as services_module

        # services.py imports MAX_RULES_PER_VERSION by value from models.py
        # at load time, so the module-level name (not a settings key) is
        # what add_policy_rule() actually checks.
        monkeypatch.setattr(services_module, "MAX_RULES_PER_VERSION", 1)
        workspace = WorkspaceFactory()
        actor = UserFactory()
        policy = services.create_policy(workspace=workspace, actor=actor, name="Refunds")
        version = services.create_policy_version(workspace=workspace, policy=policy, actor=actor)
        services.add_policy_rule(
            workspace=workspace,
            policy_version=version,
            actor=actor,
            data={"name": "r1", "priority": 0, "effect": "allow"},
        )
        with pytest.raises(PolicyLimitExceededError):
            services.add_policy_rule(
                workspace=workspace,
                policy_version=version,
                actor=actor,
                data={"name": "r2", "priority": 1, "effect": "allow"},
            )

    def test_add_rule_persists_expected_fields(self):
        workspace = WorkspaceFactory()
        actor = UserFactory()
        policy = services.create_policy(workspace=workspace, actor=actor, name="Refunds")
        version = services.create_policy_version(workspace=workspace, policy=policy, actor=actor)
        rule = services.add_policy_rule(
            workspace=workspace,
            policy_version=version,
            actor=actor,
            data={
                "name": "deny-large",
                "priority": 5,
                "effect": "deny",
                "tool_key": "payment.refund",
                "condition_config": {"all": [{"predicate": "amount_minor_gt", "value": 100000}]},
            },
        )
        assert PolicyRule.objects.filter(pk=rule.pk, policy_version=version).exists()
        assert rule.tool_key == "payment.refund"
