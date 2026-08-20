"""Policy model constraint tests (section 87, 120-121)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from policies.models import PolicyStatus, PolicyVersionStatus
from policies.tests.factories import PolicyFactory, PolicyRuleFactory, PolicyVersionFactory
from workspaces.tests.factories import WorkspaceFactory


@pytest.mark.django_db
class TestPolicyConstraints:
    def test_only_one_active_policy_per_workspace(self):
        workspace = WorkspaceFactory()
        PolicyFactory(workspace=workspace, status=PolicyStatus.ACTIVE)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PolicyFactory(workspace=workspace, status=PolicyStatus.ACTIVE)

    def test_two_workspaces_may_each_have_an_active_policy(self):
        PolicyFactory(workspace=WorkspaceFactory(), status=PolicyStatus.ACTIVE)
        PolicyFactory(workspace=WorkspaceFactory(), status=PolicyStatus.ACTIVE)  # no error

    def test_inactive_policies_are_unconstrained(self):
        workspace = WorkspaceFactory()
        PolicyFactory(workspace=workspace, status=PolicyStatus.INACTIVE)
        PolicyFactory(workspace=workspace, status=PolicyStatus.INACTIVE)  # no error

    def test_policy_name_unique_per_workspace(self):
        workspace = WorkspaceFactory()
        PolicyFactory(workspace=workspace, name="Refund policy")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PolicyFactory(workspace=workspace, name="Refund policy")

    def test_only_one_active_version_per_policy(self):
        policy = PolicyFactory()
        PolicyVersionFactory(policy=policy, version=1, status=PolicyVersionStatus.ACTIVE)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PolicyVersionFactory(policy=policy, version=2, status=PolicyVersionStatus.ACTIVE)

    def test_str_methods_are_safe_and_informative(self):
        policy = PolicyFactory(name="Refunds")
        version = PolicyVersionFactory(policy=policy, version=3)
        rule = PolicyRuleFactory(policy_version=version, name="deny-large")
        assert "Refunds" in str(policy)
        assert "v3" in str(version)
        assert "deny-large" in str(rule)


@pytest.mark.django_db
class TestPolicyRuleValidation:
    def test_unknown_risk_level_is_rejected(self):
        version = PolicyVersionFactory()
        rule = PolicyRuleFactory.build(policy_version=version, risk_levels=["not_a_level"])
        with pytest.raises(ValidationError):
            rule.clean()

    def test_unknown_side_effect_type_is_rejected(self):
        version = PolicyVersionFactory()
        rule = PolicyRuleFactory.build(policy_version=version, side_effect_types=["not_a_type"])
        with pytest.raises(ValidationError):
            rule.clean()

    def test_valid_risk_levels_and_side_effect_types_pass(self):
        version = PolicyVersionFactory()
        rule = PolicyRuleFactory.build(
            policy_version=version, risk_levels=["high"], side_effect_types=["financial"]
        )
        rule.clean()  # no error
