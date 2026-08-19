"""Direct selector coverage: tenant-scoped 404 behavior (section 55)."""

from __future__ import annotations

import uuid

import pytest
from django.http import Http404

from agents.tests.factories import AgentVersionFactory
from workspaces.tests.factories import WorkspaceFactory

from .. import selectors
from .factories import ToolBindingFactory, ToolExecutionFactory


@pytest.mark.django_db
class TestToolBindingSelectors:
    def test_list_for_version_scoped_to_workspace(self):
        binding = ToolBindingFactory()
        workspace = binding.agent_version.agent_definition.workspace
        results = selectors.tool_binding_list_for_version(
            workspace=workspace, agent_version=binding.agent_version
        )
        assert list(results) == [binding]

    def test_get_for_workspace_or_404_hit(self):
        binding = ToolBindingFactory()
        workspace = binding.agent_version.agent_definition.workspace
        found = selectors.tool_binding_get_for_workspace_or_404(
            workspace=workspace, agent_version=binding.agent_version, binding_id=binding.id
        )
        assert found.id == binding.id

    def test_get_for_workspace_or_404_miss(self):
        binding = ToolBindingFactory()
        with pytest.raises(Http404):
            selectors.tool_binding_get_for_workspace_or_404(
                workspace=WorkspaceFactory(),
                agent_version=binding.agent_version,
                binding_id=binding.id,
            )

    def test_get_for_workspace_or_404_unknown_id(self):
        version = AgentVersionFactory()
        with pytest.raises(Http404):
            selectors.tool_binding_get_for_workspace_or_404(
                workspace=version.agent_definition.workspace,
                agent_version=version,
                binding_id=uuid.uuid4(),
            )


@pytest.mark.django_db
class TestToolExecutionSelectors:
    def test_get_for_workspace_or_404_miss(self):
        execution = ToolExecutionFactory()
        with pytest.raises(Http404):
            selectors.tool_execution_get_for_workspace_or_404(
                workspace=WorkspaceFactory(), execution_id=execution.id
            )

    def test_list_filters_by_invalid_agent_run_id_returns_empty(self):
        execution = ToolExecutionFactory()
        results = selectors.tool_execution_list_for_workspace(
            workspace=execution.workspace, agent_run_id="not-a-uuid"
        )
        assert list(results) == []

    def test_list_filters_by_valid_agent_run_id(self):
        execution = ToolExecutionFactory()
        results = selectors.tool_execution_list_for_workspace(
            workspace=execution.workspace, agent_run_id=str(execution.agent_run_id)
        )
        assert list(results) == [execution]

    def test_list_filters_by_status(self):
        execution = ToolExecutionFactory()
        matching = selectors.tool_execution_list_for_workspace(
            workspace=execution.workspace, status="pending"
        )
        non_matching = selectors.tool_execution_list_for_workspace(
            workspace=execution.workspace, status="succeeded"
        )
        assert list(matching) == [execution]
        assert list(non_matching) == []
