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
    tool_definition, _ = ToolDefinition.objects.get_or_create(
        key=key,
        defaults={
            "display_name": key,
            "handler_key": key,
            "default_timeout_seconds": 10,
            "max_timeout_seconds": 15,
        },
    )
    ToolBinding.objects.get_or_create(
        agent_version=run.agent_version, tool_definition=tool_definition, defaults={"enabled": True}
    )
    return tool_definition
