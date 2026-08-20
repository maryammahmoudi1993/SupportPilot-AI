"""Integration-domain test factories and shared execute_tool helpers."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from agents.models import AgentRunStatus
from agents.tests.factories import AgentRunFactory, PublishedAgentVersionFactory
from integrations.crypto import encrypt_credentials
from integrations.models import (
    IntegrationConnection,
    IntegrationConnectionStatus,
    IntegrationEnvironment,
    IntegrationProvider,
)
from tools.models import ToolBinding, ToolDefinition
from workspaces.tests.factories import WorkspaceFactory


class IntegrationConnectionFactory(DjangoModelFactory):
    class Meta:
        model = IntegrationConnection

    workspace = factory.SubFactory(WorkspaceFactory)
    provider = IntegrationProvider.STRIPE
    display_name = "Test connection"
    status = IntegrationConnectionStatus.ACTIVE
    environment = IntegrationEnvironment.TEST
    credential_version = 1

    @factory.lazy_attribute
    def encrypted_credentials(self):
        defaults = {
            IntegrationProvider.STRIPE: {"secret_key": "sk_test_fake_1234567890"},
            IntegrationProvider.GOOGLE_CALENDAR: {
                "service_account_info": {"type": "service_account"}
            },
            IntegrationProvider.EMAIL: {
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password": "pw",
                "use_tls": True,
            },
            IntegrationProvider.DEMO_COMMERCE: {},
        }
        return encrypt_credentials(defaults[self.provider])


def running_run(**kwargs):
    """An AgentRun in ``RUNNING`` status, ready for ``execute_tool``."""
    max_tool_calls = kwargs.pop("max_tool_calls", 5)
    version = PublishedAgentVersionFactory(max_tool_calls=max_tool_calls)
    workspace = kwargs.pop("workspace", version.agent_definition.workspace)
    return AgentRunFactory(
        agent_version=version, workspace=workspace, status=AgentRunStatus.RUNNING, **kwargs
    )


def allow_all_policy(workspace):
    """Phase 8 helper: activate a trivial workspace policy that ALLOWs every
    tool unconditionally. Several Phase 7 tests exercise handler/provider
    mechanics for tools the Phase 8 system default now gates behind approval
    (``calendar.create_booking``, ``notification.send``) — those tests are
    about Phase 7 execution correctness, not Phase 8 authorization, so they
    opt into an explicit permissive policy rather than asserting against the
    system default."""
    from policies.models import (
        Policy,
        PolicyEffect,
        PolicyRule,
        PolicyStatus,
        PolicyVersion,
        PolicyVersionStatus,
    )

    policy = Policy.objects.create(
        workspace=workspace, name="Allow all (test)", status=PolicyStatus.ACTIVE
    )
    version = PolicyVersion.objects.create(
        policy=policy, version=1, status=PolicyVersionStatus.ACTIVE
    )
    PolicyRule.objects.create(
        policy_version=version,
        name="allow-all",
        priority=0,
        effect=PolicyEffect.ALLOW,
        condition_config={"all": []},
    )
    return policy


def bind_tool(run, key: str) -> ToolDefinition:
    """Get-or-create the ``ToolDefinition`` row for ``key`` and bind it onto
    ``run``'s agent version.

    Deliberately does not depend on the Phase 7 seed migration's rows
    surviving test isolation: several of these tests use
    ``transaction=True`` (execute_tool dispatches the handler on a worker
    thread, which needs a *committed*, cross-connection-visible workspace —
    see the module docstring in test_tools_payment.py), and a
    ``TransactionTestCase``-style test flushes all tables — including
    migration-inserted data — between tests unless the run configures
    serialized-rollback fixtures, which this project's baseline does not.
    ``get_or_create`` makes this factory correct either way, mirroring
    ``tools.tests.factories.ToolDefinitionFactory``'s own
    ``django_get_or_create`` pattern.
    """
    # Source risk_level/side_effect_type from the code-owned registry (never
    # a hardcoded guess) so a fresh row created here — e.g. under a
    # ``transaction=True`` test whose flush wiped the seed migration's rows
    # — still carries the same policy-relevant metadata as production,
    # instead of silently falling back to the model's LOW/NONE defaults and
    # producing a misleadingly permissive Phase 8 policy decision.
    from tools.registry import registry as tool_registry

    defaults = {
        "display_name": key,
        "handler_key": key,
        "default_timeout_seconds": 10,
        "max_timeout_seconds": 15,
    }
    try:
        spec = tool_registry.get(key).spec
        defaults["risk_level"] = spec.risk_level
        defaults["side_effect_type"] = spec.side_effect_type
    except Exception:  # pragma: no cover - defensive, only demo/unregistered keys
        pass
    tool_definition, _ = ToolDefinition.objects.get_or_create(key=key, defaults=defaults)
    ToolBinding.objects.get_or_create(
        agent_version=run.agent_version, tool_definition=tool_definition, defaults={"enabled": True}
    )
    return tool_definition
