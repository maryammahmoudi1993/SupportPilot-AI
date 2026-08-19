"""API surface: RBAC, tenant isolation, catalog listing, binding CRUD,
execution history (section 91)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from agents.tests.factories import AgentDefinitionFactory, PublishedAgentVersionFactory
from workspaces.models import WorkspaceRole
from workspaces.tests.factories import WorkspaceMembershipFactory

from .factories import ToolBindingFactory, ToolDefinitionFactory, ToolExecutionFactory


def _client(user=None):
    client = APIClient()
    if user:
        client.force_authenticate(user=user)
    return client


def _tools_base(workspace):
    return f"/api/v1/workspaces/{workspace.id}/tools"


def _bindings_base(workspace, agent_id, version_id):
    return (
        f"/api/v1/workspaces/{workspace.id}/agents/{agent_id}/versions/{version_id}/tool-bindings"
    )


@pytest.mark.django_db
class TestToolCatalogApi:
    def test_anonymous_is_401(self):
        membership = WorkspaceMembershipFactory()
        assert _client().get(f"{_tools_base(membership.workspace)}/").status_code == 401

    def test_any_member_can_list_the_catalog(self):
        ToolDefinitionFactory(key="demo.echo")
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        response = _client(membership.user).get(f"{_tools_base(membership.workspace)}/")
        assert response.status_code == 200
        assert any(t["key"] == "demo.echo" for t in response.data["results"])

    def test_catalog_never_exposes_handler_internals(self):
        ToolDefinitionFactory(key="demo.echo")
        membership = WorkspaceMembershipFactory()
        response = _client(membership.user).get(f"{_tools_base(membership.workspace)}/")
        payload = response.data["results"][0]
        assert "handler_key" not in payload
        assert set(payload.keys()) == {
            "id",
            "key",
            "display_name",
            "description",
            "status",
            "risk_level",
            "side_effect_type",
            "default_timeout_seconds",
            "max_timeout_seconds",
            "max_retries",
            "idempotency_mode",
        }


@pytest.mark.django_db
class TestToolBindingApi:
    @pytest.mark.parametrize(
        "role,allowed",
        [
            (WorkspaceRole.OWNER, True),
            (WorkspaceRole.ADMIN, True),
            (WorkspaceRole.SUPPORT_MANAGER, True),
            (WorkspaceRole.SUPPORT_AGENT, False),
            (WorkspaceRole.VIEWER, False),
        ],
    )
    def test_binding_creation_rbac(self, role, allowed):
        tool = ToolDefinitionFactory(key="demo.echo")
        membership = WorkspaceMembershipFactory(role=role)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        # Bindings only attach to a draft version (published versions are immutable).
        from agents.tests.factories import AgentVersionFactory

        draft = AgentVersionFactory(agent_definition=definition)
        response = _client(membership.user).post(
            _bindings_base(membership.workspace, definition.id, draft.id) + "/",
            {"tool_key": tool.key},
            format="json",
        )
        assert response.status_code == (201 if allowed else 403)

    def test_binding_on_published_version_is_rejected(self):
        tool = ToolDefinitionFactory(key="demo.echo")
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        version = PublishedAgentVersionFactory(agent_definition=definition)
        response = _client(membership.user).post(
            _bindings_base(membership.workspace, definition.id, version.id) + "/",
            {"tool_key": tool.key},
            format="json",
        )
        assert response.status_code == 409

    def test_oversized_configuration_is_rejected(self):
        tool = ToolDefinitionFactory(key="demo.echo")
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        from agents.tests.factories import AgentVersionFactory

        draft = AgentVersionFactory(agent_definition=definition)
        response = _client(membership.user).post(
            _bindings_base(membership.workspace, definition.id, draft.id) + "/",
            {"tool_key": tool.key, "configuration": {"note": "x" * 3000}},
            format="json",
        )
        assert response.status_code == 400

    def test_unknown_tool_key_is_404(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        from agents.tests.factories import AgentVersionFactory

        draft = AgentVersionFactory(agent_definition=definition)
        response = _client(membership.user).post(
            _bindings_base(membership.workspace, definition.id, draft.id) + "/",
            {"tool_key": "does.not.exist"},
            format="json",
        )
        assert response.status_code == 404

    def test_client_cannot_set_server_derived_fields(self):
        tool = ToolDefinitionFactory(key="demo.echo")
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        from agents.tests.factories import AgentVersionFactory

        draft = AgentVersionFactory(agent_definition=definition)
        response = _client(membership.user).post(
            _bindings_base(membership.workspace, definition.id, draft.id) + "/",
            {"tool_key": tool.key, "enabled": False, "id": "11111111-1111-1111-1111-111111111111"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["enabled"] is True  # server default, ignoring client input
        assert response.data["id"] != "11111111-1111-1111-1111-111111111111"

    def test_disable_binding_toggle(self):
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        definition = AgentDefinitionFactory(workspace=membership.workspace)
        from agents.tests.factories import AgentVersionFactory

        draft = AgentVersionFactory(agent_definition=definition)
        binding = ToolBindingFactory(agent_version=draft)
        response = _client(membership.user).patch(
            f"{_bindings_base(membership.workspace, definition.id, draft.id)}/{binding.id}/",
            {"enabled": False},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["enabled"] is False

    def test_foreign_workspace_binding_is_404(self):
        binding = ToolBindingFactory()
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        base = _bindings_base(
            membership.workspace,
            binding.agent_version.agent_definition_id,
            binding.agent_version_id,
        )
        response = _client(membership.user).patch(
            f"{base}/{binding.id}/", {"enabled": False}, format="json"
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestToolExecutionApi:
    def test_execution_listing_is_tenant_scoped(self):
        own = ToolExecutionFactory()  # a different workspace's execution
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.VIEWER)
        from agents.tests.factories import AgentRunFactory
        from agents.tests.factories import PublishedAgentVersionFactory as PV

        version = PV(agent_definition__workspace=membership.workspace)
        run = AgentRunFactory(agent_version=version, workspace=membership.workspace)
        mine = ToolExecutionFactory(
            agent_run=run, workspace=membership.workspace, agent_version=version
        )
        response = _client(membership.user).get(
            f"{_tools_base(membership.workspace)}/tool-executions/"
        )
        assert response.status_code == 200
        ids = {row["id"] for row in response.data["results"]}
        assert str(mine.id) in ids
        assert str(own.id) not in ids

    def test_cross_tenant_execution_detail_is_404_not_403(self):
        execution = ToolExecutionFactory()
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        response = _client(membership.user).get(
            f"{_tools_base(membership.workspace)}/tool-executions/{execution.id}/"
        )
        assert response.status_code == 404

    def test_execution_detail_never_exposes_raw_secrets(self):
        execution = ToolExecutionFactory(
            arguments_redacted={"api_token": "***REDACTED***", "note": "hi"}
        )
        membership = WorkspaceMembershipFactory(role=WorkspaceRole.OWNER)
        execution.workspace = membership.workspace
        execution.save()
        response = _client(membership.user).get(
            f"{_tools_base(membership.workspace)}/tool-executions/{execution.id}/"
        )
        assert response.status_code == 200
        assert response.data["arguments_redacted"]["api_token"] == "***REDACTED***"
