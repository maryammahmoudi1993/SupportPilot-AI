"""Typed, trusted tool contracts.

Every tool the runtime can invoke is a server-owned Python object built from
this module — never a database-stored callable, import path, or arbitrary
code. A ``ToolSpec`` is immutable configuration; a concrete tool pairs a spec
with a handler function that receives *trusted* ``ToolExecutionContext`` and
*untrusted*, schema-validated ``arguments`` separately (see section 19-20 of
the Phase 6 brief) and returns a typed, schema-validated result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from django.db import models
from pydantic import BaseModel


class RiskLevel(models.TextChoices):
    """Descriptive only in Phase 6 — policy/approval enforcement is a later
    phase. No execution decision in this phase branches on risk level."""

    READ_ONLY = "read_only", "Read only"
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class SideEffectType(models.TextChoices):
    NONE = "none", "None"
    READ = "read", "Read"
    INTERNAL_WRITE = "internal_write", "Internal write"
    EXTERNAL_WRITE = "external_write", "External write"
    FINANCIAL = "financial", "Financial"
    DESTRUCTIVE = "destructive", "Destructive"


class IdempotencyMode(models.TextChoices):
    """Whether a handler may safely be replayed for the same idempotency key.

    ``NONE`` tools do not accept an idempotency key at all. ``SAFE`` tools
    declare that calling the handler twice with identical arguments is
    harmless (e.g. pure reads) — the execution service still short-circuits
    on a stored key for consistency, but the classification exists so future
    policy can distinguish "replay is cosmetic" from "replay would double a
    side effect".
    """

    NONE = "none", "None"
    SAFE = "safe", "Safe to retry/replay"
    REQUIRED = "required", "Requires a caller-supplied key"


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded, explicit retry configuration for one tool.

    ``retryable_error_codes`` is the only classification the execution
    service trusts to decide whether a failed attempt may be retried — an
    error code absent from this set is treated as non-retryable regardless
    of how many attempts remain.
    """

    max_retries: int = 0
    retryable_error_codes: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")


@dataclass(frozen=True)
class ToolSpec:
    """Trusted, code-owned metadata describing one registered tool.

    ``key`` is the stable, machine-safe canonical identifier referenced by
    persisted execution history — it must never be renamed once used.
    """

    key: str
    display_name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk_level: str = RiskLevel.LOW
    side_effect_type: str = SideEffectType.NONE
    default_timeout_seconds: float = 5.0
    max_timeout_seconds: float = 10.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    idempotency_mode: str = IdempotencyMode.SAFE
    input_sensitive_fields: frozenset[str] = field(default_factory=frozenset)
    output_sensitive_fields: frozenset[str] = field(default_factory=frozenset)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.key or not self.key.strip():
            raise ValueError("Tool key must not be blank.")
        if self.key != self.key.strip():
            raise ValueError("Tool key must not have leading/trailing whitespace.")
        if self.default_timeout_seconds <= 0 or self.max_timeout_seconds <= 0:
            raise ValueError("Timeouts must be positive.")
        if self.default_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("default_timeout_seconds cannot exceed max_timeout_seconds.")


@dataclass(frozen=True)
class ToolExecutionContext:
    """Trusted, server-derived execution scope.

    Every field here is set by the execution service from authenticated,
    server-side state — never from model-generated arguments. Handlers must
    treat this as the only source of tenant/run identity (section 19-20).
    """

    workspace_id: str
    tool_execution_id: str
    correlation_id: str | None
    deadline: datetime
    agent_run_id: str | None = None
    agent_version_id: str | None = None
    actor_user_id: str | None = None


class ToolHandler(Protocol):
    """The trusted callable signature every registered tool implements."""

    def __call__(self, *, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel: ...


@dataclass(frozen=True)
class Tool:
    """A registered tool: immutable metadata plus its trusted handler."""

    spec: ToolSpec
    handler: ToolHandler

    def execute(self, *, context: ToolExecutionContext, arguments: BaseModel) -> BaseModel:
        return self.handler(context=context, arguments=arguments)
