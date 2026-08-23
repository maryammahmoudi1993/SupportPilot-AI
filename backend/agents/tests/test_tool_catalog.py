"""Trusted, tenant-scoped provider tool catalog discovery."""

from __future__ import annotations

import pytest

from agents.tests.factories import AgentVersionFactory, PublishedAgentVersionFactory
from agents.tool_catalog import ToolCatalogConfigurationError, get_bound_tool_descriptors
from tools.models import ToolDefinitionStatus
from tools.registry import registry
from tools.tests.factories import ToolBindingFactory, ToolDefinitionFactory
from workspaces.tests.factories import WorkspaceFactory


@pytest.mark.django_db
class TestBoundToolCatalog:
    def test_only_enabled_bound_tools_are_exposed_in_stable_order(self):
        version = PublishedAgentVersionFactory()
        add = ToolDefinitionFactory(key="demo.add", handler_key="demo.add")
        echo = ToolDefinitionFactory(key="demo.echo", handler_key="demo.echo")
        flaky = ToolDefinitionFactory(key="demo.flaky", handler_key="demo.flaky")
        ToolBindingFactory(agent_version=version, tool_definition=echo)
        ToolBindingFactory(agent_version=version, tool_definition=add)
        ToolBindingFactory(agent_version=version, tool_definition=flaky, enabled=False)

        descriptors = get_bound_tool_descriptors(
            agent_version=version, workspace=version.agent_definition.workspace
        )

        assert [item.key for item in descriptors] == ["demo.add", "demo.echo"]
        assert descriptors[0].input_schema["required"] == ["a", "b"]
        assert descriptors[0].input_schema["properties"]["a"]["type"] == "integer"
        assert descriptors[0].input_schema["additionalProperties"] is False
        forbidden = {
            "workspace_id",
            "agent_run_id",
            "agent_version_id",
            "tool_execution_id",
            "approved",
            "policy_decision",
            "risk",
            "integration_credential",
            "timeout_override",
            "retry_override",
        }
        assert forbidden.isdisjoint(descriptors[0].input_schema["properties"])
        assert "system.shell" not in {item.key for item in descriptors}

    def test_inactive_definition_is_hidden(self):
        version = PublishedAgentVersionFactory()
        definition = ToolDefinitionFactory(key="demo.echo", handler_key="demo.echo")
        definition.status = ToolDefinitionStatus.DISABLED
        definition.save(update_fields=["status", "updated_at"])
        ToolBindingFactory(agent_version=version, tool_definition=definition)

        assert (
            get_bound_tool_descriptors(
                agent_version=version, workspace=version.agent_definition.workspace
            )
            == ()
        )

    @pytest.mark.parametrize("mismatch", ["missing_registry", "handler_key"])
    def test_registry_or_handler_mismatch_fails_closed(self, mismatch):
        version = PublishedAgentVersionFactory()
        if mismatch == "missing_registry":
            definition = ToolDefinitionFactory(key="not.registered", handler_key="not.registered")
        else:
            definition = ToolDefinitionFactory(key="demo.echo")
            definition.handler_key = "import.this"
            definition.save(update_fields=["handler_key", "updated_at"])
        ToolBindingFactory(agent_version=version, tool_definition=definition)

        with pytest.raises(ToolCatalogConfigurationError):
            get_bound_tool_descriptors(
                agent_version=version, workspace=version.agent_definition.workspace
            )

    def test_cross_tenant_and_unpublished_versions_fail_closed(self):
        version = PublishedAgentVersionFactory()
        with pytest.raises(ToolCatalogConfigurationError):
            get_bound_tool_descriptors(agent_version=version, workspace=WorkspaceFactory())

        draft = AgentVersionFactory()
        with pytest.raises(ToolCatalogConfigurationError):
            get_bound_tool_descriptors(
                agent_version=draft, workspace=draft.agent_definition.workspace
            )

    def test_catalog_never_enumerates_unbound_global_registry(self):
        version = PublishedAgentVersionFactory()
        assert {tool.spec.key for tool in registry.list()}
        assert (
            get_bound_tool_descriptors(
                agent_version=version, workspace=version.agent_definition.workspace
            )
            == ()
        )
