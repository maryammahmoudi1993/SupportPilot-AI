"""Direct unit coverage for catalog sync and binding-configuration services
(section 21-23, 56-57) — separate from the API-level RBAC tests."""

from __future__ import annotations

import pytest

from agents.errors import AgentVersionImmutableError
from agents.tests.factories import AgentVersionFactory, PublishedAgentVersionFactory
from audit.models import AuditAction, AuditEvent
from tools import services
from tools.errors import ToolConfigurationError
from tools.models import ToolDefinitionStatus
from tools.registry import registry as production_registry

from .factories import ToolBindingFactory, ToolDefinitionFactory


@pytest.mark.django_db
class TestSyncToolDefinitions:
    def test_syncs_every_registered_tool(self):
        synced = services.sync_tool_definitions()
        keys = {d.key for d in synced}
        assert {"demo.echo", "demo.add", "demo.flaky"} <= keys

    def test_is_idempotent_and_updates_existing_rows(self):
        first = {d.key: d.id for d in services.sync_tool_definitions()}
        second = {d.key: d.id for d in services.sync_tool_definitions()}
        assert first == second  # same rows updated, not duplicated

    def test_reflects_registry_metadata(self):
        synced = {d.key: d for d in services.sync_tool_definitions()}
        echo = synced["demo.echo"]
        assert echo.risk_level == "read_only"
        assert echo.status == ToolDefinitionStatus.ACTIVE

    def test_uses_the_default_production_registry_when_unspecified(self):
        synced = {d.key: d for d in services.sync_tool_definitions(source_registry=None)}
        assert "demo.echo" in synced
        assert production_registry.get_or_none("demo.echo") is not None


@pytest.mark.django_db
class TestCreateToolBinding:
    def test_creates_binding_and_audit_event(self):
        tool = ToolDefinitionFactory(key="demo.echo")
        version = AgentVersionFactory()
        actor = version.created_by

        binding = services.create_tool_binding(
            workspace=version.agent_definition.workspace,
            agent_version=version,
            actor=actor,
            tool_definition=tool,
        )
        assert binding.tool_definition_id == tool.id
        assert AuditEvent.objects.filter(
            action=AuditAction.TOOL_BINDING_CREATED, target_id=str(binding.id)
        ).exists()

    def test_rejects_binding_a_published_version(self):
        tool = ToolDefinitionFactory(key="demo.echo")
        version = PublishedAgentVersionFactory()
        with pytest.raises(AgentVersionImmutableError):
            services.create_tool_binding(
                workspace=version.agent_definition.workspace,
                agent_version=version,
                actor=version.created_by,
                tool_definition=tool,
            )

    def test_rejects_binding_a_disabled_tool(self):
        tool = ToolDefinitionFactory(key="test.disabled_tool", status=ToolDefinitionStatus.DISABLED)
        version = AgentVersionFactory()
        with pytest.raises(ToolConfigurationError):
            services.create_tool_binding(
                workspace=version.agent_definition.workspace,
                agent_version=version,
                actor=version.created_by,
                tool_definition=tool,
            )


@pytest.mark.django_db
class TestSetToolBindingEnabled:
    def test_disabling_records_a_disabled_audit_event(self):
        binding = ToolBindingFactory(agent_version=AgentVersionFactory())
        actor = binding.agent_version.created_by
        services.set_tool_binding_enabled(
            workspace=binding.agent_version.agent_definition.workspace,
            binding=binding,
            actor=actor,
            enabled=False,
        )
        binding.refresh_from_db()
        assert binding.enabled is False
        assert AuditEvent.objects.filter(
            action=AuditAction.TOOL_BINDING_DISABLED, target_id=str(binding.id)
        ).exists()

    def test_re_enabling_records_an_updated_audit_event(self):
        binding = ToolBindingFactory(agent_version=AgentVersionFactory(), enabled=False)
        actor = binding.agent_version.created_by
        services.set_tool_binding_enabled(
            workspace=binding.agent_version.agent_definition.workspace,
            binding=binding,
            actor=actor,
            enabled=True,
        )
        assert AuditEvent.objects.filter(
            action=AuditAction.TOOL_BINDING_UPDATED, target_id=str(binding.id)
        ).exists()

    def test_cannot_toggle_a_binding_on_a_published_version(self):
        binding = ToolBindingFactory(agent_version=PublishedAgentVersionFactory())
        with pytest.raises(AgentVersionImmutableError):
            services.set_tool_binding_enabled(
                workspace=binding.agent_version.agent_definition.workspace,
                binding=binding,
                actor=binding.agent_version.created_by,
                enabled=False,
            )
