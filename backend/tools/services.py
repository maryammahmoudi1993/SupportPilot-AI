"""Tool catalog sync and agent-version tool-binding configuration services.

Execution itself lives in ``tools.execution`` — this module only covers the
trusted, code-owned catalog and the RBAC-gated binding CRUD used to wire a
tool onto a draft ``AgentVersion`` (section 21-23, 56-57).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from accounts.models import User
from agents.errors import AgentVersionImmutableError
from agents.models import AgentVersion, AgentVersionStatus
from audit.models import AuditAction
from audit.services import record_event
from workspaces.models import Workspace

from .contracts import Tool
from .errors import ToolConfigurationError
from .models import ToolBinding, ToolDefinition, ToolDefinitionStatus
from .registry import registry as default_registry


def sync_tool_definitions(*, source_registry=None) -> list[ToolDefinition]:
    """Idempotently mirror every registered ``Tool`` into ``ToolDefinition``.

    The registry (trusted code) is always the source of truth for identity
    and capability metadata; this only ever creates/updates rows to match
    it — it never lets a database row invent a tool the registry does not
    have. Safe to call repeatedly (e.g. from a data migration and again
    from test fixtures).
    """
    source_registry = source_registry or default_registry
    synced: list[ToolDefinition] = []
    for tool in source_registry.list():
        synced.append(_sync_one(tool))
    return synced


def _sync_one(tool: Tool) -> ToolDefinition:
    spec = tool.spec
    definition, _created = ToolDefinition.objects.update_or_create(
        key=spec.key,
        defaults={
            "display_name": spec.display_name,
            "description": spec.description,
            "status": (
                ToolDefinitionStatus.ACTIVE if spec.enabled else ToolDefinitionStatus.DISABLED
            ),
            "risk_level": spec.risk_level,
            "side_effect_type": spec.side_effect_type,
            "handler_key": spec.key,
            "default_timeout_seconds": int(spec.default_timeout_seconds),
            "max_timeout_seconds": int(spec.max_timeout_seconds),
            "max_retries": spec.retry_policy.max_retries,
            "idempotency_mode": spec.idempotency_mode,
        },
    )
    return definition


def create_tool_binding(
    *,
    workspace: Workspace,
    agent_version: AgentVersion,
    actor: User,
    tool_definition: ToolDefinition,
    configuration: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> ToolBinding:
    if agent_version.status != AgentVersionStatus.DRAFT:
        # Preserves Phase 5 published-version immutability: bindings freeze
        # once a version is published (section 22).
        raise AgentVersionImmutableError()
    if tool_definition.status != ToolDefinitionStatus.ACTIVE:
        raise ToolConfigurationError("Cannot bind a disabled tool.")
    with transaction.atomic():
        binding = ToolBinding.objects.create(
            agent_version=agent_version,
            tool_definition=tool_definition,
            configuration=configuration or {},
        )
        record_event(
            action=AuditAction.TOOL_BINDING_CREATED,
            target_type="tool_binding",
            target_id=binding.id,
            actor=actor,
            workspace=workspace,
            metadata={
                "agent_version_id": str(agent_version.id),
                "tool_key": tool_definition.key,
            },
            request_id=request_id,
        )
    return binding


def set_tool_binding_enabled(
    *,
    workspace: Workspace,
    binding: ToolBinding,
    actor: User,
    enabled: bool,
    request_id: str | None = None,
) -> ToolBinding:
    if binding.agent_version.status != AgentVersionStatus.DRAFT:
        raise AgentVersionImmutableError()
    with transaction.atomic():
        binding.enabled = enabled
        binding.save(update_fields=["enabled", "updated_at"])
        record_event(
            action=(
                AuditAction.TOOL_BINDING_DISABLED
                if not enabled
                else AuditAction.TOOL_BINDING_UPDATED
            ),
            target_type="tool_binding",
            target_id=binding.id,
            actor=actor,
            workspace=workspace,
            metadata={"enabled": enabled},
            request_id=request_id,
        )
    return binding
