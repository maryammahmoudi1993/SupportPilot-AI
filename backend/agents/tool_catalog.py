"""Provider-independent discovery of tools bound to one agent version."""

from __future__ import annotations

from agents.errors import AgentError
from agents.models import AgentVersion, AgentVersionStatus
from agents.providers.schemas import ToolDescriptor
from tools.models import ToolDefinitionStatus
from tools.registry import registry
from tools.selectors import tool_binding_list_for_version
from workspaces.models import Workspace


class ToolCatalogConfigurationError(AgentError):
    code = "tool_catalog_configuration_error"
    safe_message = "The agent's tool catalog is misconfigured."


_SERVER_OWNED_FIELDS = frozenset(
    {
        "workspace_id",
        "agent_run_id",
        "agent_version_id",
        "tool_execution_id",
        "actor_role",
        "integration_credential",
        "approved",
        "approval_override",
        "policy_decision",
        "risk",
        "timeout_override",
        "retry_override",
    }
)


def _assert_schema_has_no_server_owned_fields(schema: dict[str, object]) -> None:
    def inspect(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties", {})
            if isinstance(properties, dict) and _SERVER_OWNED_FIELDS.intersection(properties):
                raise ToolCatalogConfigurationError()
            for value in node.values():
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)

    inspect(schema)


def get_bound_tool_descriptors(
    *, agent_version: AgentVersion, workspace: Workspace
) -> tuple[ToolDescriptor, ...]:
    """Resolve enabled bindings in one query and schemas from trusted code."""
    if (
        agent_version.status != AgentVersionStatus.PUBLISHED
        or agent_version.agent_definition.workspace_id != workspace.id
    ):
        raise ToolCatalogConfigurationError()

    descriptors: list[ToolDescriptor] = []
    bindings = tool_binding_list_for_version(
        workspace=workspace, agent_version=agent_version
    ).filter(enabled=True, tool_definition__status=ToolDefinitionStatus.ACTIVE)
    for binding in bindings:
        definition = binding.tool_definition
        tool = registry.get_or_none(definition.key)
        if tool is None or not tool.spec.enabled or definition.handler_key != tool.spec.key:
            raise ToolCatalogConfigurationError()
        schema = tool.spec.input_model.model_json_schema()
        _assert_schema_has_no_server_owned_fields(schema)
        descriptors.append(
            ToolDescriptor(
                key=tool.spec.key,
                display_name=tool.spec.display_name,
                description=tool.spec.description,
                input_schema=schema,
            )
        )
    return tuple(sorted(descriptors, key=lambda descriptor: descriptor.key))
