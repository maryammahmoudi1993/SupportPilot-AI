"""Policy-domain test factories."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from accounts.tests.factories import UserFactory
from policies.models import (
    Policy,
    PolicyEffect,
    PolicyRule,
    PolicyStatus,
    PolicyVersion,
    PolicyVersionStatus,
)
from workspaces.tests.factories import WorkspaceFactory


class PolicyFactory(DjangoModelFactory):
    class Meta:
        model = Policy

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f"Policy {n}")
    status = PolicyStatus.DRAFT
    created_by = factory.SubFactory(UserFactory)


class PolicyVersionFactory(DjangoModelFactory):
    class Meta:
        model = PolicyVersion

    policy = factory.SubFactory(PolicyFactory)
    version = 1
    status = PolicyVersionStatus.DRAFT
    created_by = factory.SubFactory(UserFactory)


class PolicyRuleFactory(DjangoModelFactory):
    class Meta:
        model = PolicyRule

    policy_version = factory.SubFactory(PolicyVersionFactory)
    name = factory.Sequence(lambda n: f"rule-{n}")
    priority = 0
    enabled = True
    effect = PolicyEffect.ALLOW
    condition_config: dict = {}


def active_version_with_rules(*, workspace, rules: list[dict]):
    """A workspace's single active Policy/PolicyVersion with the given rule
    kwargs applied on top of ``PolicyRuleFactory`` defaults."""
    policy = PolicyFactory(workspace=workspace, status=PolicyStatus.ACTIVE)
    version = PolicyVersionFactory(policy=policy, status=PolicyVersionStatus.ACTIVE)
    for kwargs in rules:
        PolicyRuleFactory(policy_version=version, **kwargs)
    return version
