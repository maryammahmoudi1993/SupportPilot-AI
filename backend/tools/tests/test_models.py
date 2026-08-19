"""Model-level constraint tests (section 72)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from tools.models import ToolDefinition, ToolExecutionStatus
from workspaces.tests.factories import WorkspaceFactory

from .factories import ToolBindingFactory, ToolDefinitionFactory, ToolExecutionFactory


@pytest.mark.django_db
class TestToolDefinitionConstraints:
    def test_key_must_be_unique(self):
        ToolDefinitionFactory(key="demo.echo")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ToolDefinition.objects.create(
                    key="demo.echo", display_name="dup", handler_key="demo.echo"
                )

    def test_blank_key_rejected_at_db_level(self):
        definition = ToolDefinitionFactory.build(key="")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                definition.save()

    def test_risk_and_side_effect_metadata_persist(self):
        definition = ToolDefinitionFactory(
            key="test.risk_metadata", risk_level="high", side_effect_type="financial"
        )
        definition.refresh_from_db()
        assert definition.risk_level == "high"
        assert definition.side_effect_type == "financial"

    def test_enabled_property_reflects_status(self):
        active = ToolDefinitionFactory(key="active.tool", status="active")
        disabled = ToolDefinitionFactory(key="disabled.tool", status="disabled")
        assert active.enabled is True
        assert disabled.enabled is False

    def test_str_is_the_key(self):
        definition = ToolDefinitionFactory(key="test.str_tool")
        assert str(definition) == "test.str_tool"


@pytest.mark.django_db
class TestToolBindingConstraints:
    def test_unique_per_version_and_tool(self):
        binding = ToolBindingFactory()
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ToolBindingFactory(
                    agent_version=binding.agent_version, tool_definition=binding.tool_definition
                )

    def test_same_tool_can_bind_to_different_versions(self):
        tool = ToolDefinitionFactory()
        first = ToolBindingFactory(tool_definition=tool)
        second = ToolBindingFactory(tool_definition=tool)
        assert first.agent_version_id != second.agent_version_id

    def test_enable_disable_toggle_persists(self):
        binding = ToolBindingFactory(enabled=True)
        binding.enabled = False
        binding.save()
        binding.refresh_from_db()
        assert binding.enabled is False

    def test_str_includes_version_and_tool_ids(self):
        binding = ToolBindingFactory()
        assert str(binding) == f"{binding.agent_version_id}:{binding.tool_definition_id}"


@pytest.mark.django_db
class TestToolExecutionConstraints:
    def test_defaults(self):
        execution = ToolExecutionFactory()
        assert execution.status == ToolExecutionStatus.PENDING
        assert execution.attempt_count == 0

    def test_str_includes_id_tool_and_status(self):
        execution = ToolExecutionFactory()
        assert str(execution) == f"{execution.id}:{execution.tool_definition_id}:pending"

    def test_attempt_count_cannot_be_negative(self):
        execution = ToolExecutionFactory.build(attempt_count=-1)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                execution.save()

    def test_timeout_must_be_positive(self):
        execution = ToolExecutionFactory.build(timeout_seconds=0)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                execution.save()

    def test_idempotency_key_unique_per_workspace_and_tool(self):
        execution = ToolExecutionFactory(idempotency_key="abc")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ToolExecutionFactory(
                    workspace=execution.workspace,
                    agent_run=execution.agent_run,
                    agent_version=execution.agent_version,
                    tool_definition=execution.tool_definition,
                    tool_binding=execution.tool_binding,
                    idempotency_key="abc",
                )

    def test_blank_idempotency_key_does_not_collide(self):
        execution = ToolExecutionFactory(idempotency_key="")
        second = ToolExecutionFactory(
            workspace=execution.workspace,
            agent_run=execution.agent_run,
            agent_version=execution.agent_version,
            tool_definition=execution.tool_definition,
            tool_binding=execution.tool_binding,
            idempotency_key="",
        )
        assert second.id != execution.id

    def test_idempotency_key_can_repeat_across_different_tools(self):
        execution = ToolExecutionFactory(idempotency_key="shared-key")
        other_tool = ToolDefinitionFactory(key="demo.add", handler_key="demo.add")
        other_binding = ToolBindingFactory(
            agent_version=execution.agent_version, tool_definition=other_tool
        )
        second = ToolExecutionFactory(
            workspace=execution.workspace,
            agent_run=execution.agent_run,
            agent_version=execution.agent_version,
            tool_definition=other_tool,
            tool_binding=other_binding,
            idempotency_key="shared-key",
        )
        assert second.id != execution.id

    def test_clean_rejects_cross_workspace_run(self):
        execution = ToolExecutionFactory.build(workspace=WorkspaceFactory())
        with pytest.raises(ValidationError):
            execution.full_clean()
