"""Persisted tool configuration and execution records.

``ToolDefinition`` is a queryable, bindable *mirror* of a code-owned
``tools.registry`` entry — never a place to store executable code, import
strings, or secrets (section 13-14). It is kept in sync with the registry by
``tools.services.sync_tool_definitions`` (called from a data migration and
from test fixtures), not by trusting client input.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from common.models import BaseModel

from .contracts import IdempotencyMode, RiskLevel, SideEffectType


class ToolDefinitionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class ToolExecutionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    TIMED_OUT = "timed_out", "Timed out"
    CANCELLED = "cancelled", "Cancelled"
    # Phase 8: the deterministic policy gate paused this execution pending a
    # human decision. Non-terminal — the only status besides PENDING that
    # may transition to RUNNING (see tools/execution.py::resume_after_approval).
    WAITING_FOR_APPROVAL = "waiting_for_approval", "Waiting for approval"
    # Phase 8: the deterministic policy gate denied this action outright.
    # Terminal — the handler was never invoked (section 60).
    BLOCKED_BY_POLICY = "blocked_by_policy", "Blocked by policy"
    # Phase 8: a pending approval was rejected, expired, or cancelled before
    # a decision could resume execution. Terminal — kept distinct from plain
    # CANCELLED (a directly cancelled run/execution) so that the same
    # idempotency key never re-enters the policy gate with a stale
    # RiskAssessment/PolicyEvaluation/ApprovalRequest already attached to
    # this row (see ``_resolve_existing``). The specific reason is recorded
    # in ``error_code`` (``approval_rejected`` / ``approval_expired`` /
    # ``approval_cancelled``).
    APPROVAL_TERMINATED = "approval_terminated", "Approval terminated"


TOOL_EXECUTION_TERMINAL_STATUSES = frozenset(
    {
        ToolExecutionStatus.SUCCEEDED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.TIMED_OUT,
        ToolExecutionStatus.CANCELLED,
        ToolExecutionStatus.BLOCKED_BY_POLICY,
        ToolExecutionStatus.APPROVAL_TERMINATED,
    }
)

# Terminal states never reopen (section 26). WAITING_FOR_APPROVAL is the one
# non-terminal pause state Phase 8 adds: it may resume to RUNNING (approved),
# terminate at APPROVAL_TERMINATED (rejected/expired), or CANCELLED (the
# underlying run/execution was cancelled outright while waiting, section 46).
TOOL_EXECUTION_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    ToolExecutionStatus.PENDING: frozenset(
        {
            ToolExecutionStatus.RUNNING,
            ToolExecutionStatus.CANCELLED,
            ToolExecutionStatus.WAITING_FOR_APPROVAL,
            ToolExecutionStatus.BLOCKED_BY_POLICY,
        }
    ),
    ToolExecutionStatus.RUNNING: frozenset(
        {
            ToolExecutionStatus.SUCCEEDED,
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.TIMED_OUT,
            ToolExecutionStatus.CANCELLED,
        }
    ),
    ToolExecutionStatus.WAITING_FOR_APPROVAL: frozenset(
        {
            ToolExecutionStatus.RUNNING,
            ToolExecutionStatus.APPROVAL_TERMINATED,
            ToolExecutionStatus.CANCELLED,
        }
    ),
    ToolExecutionStatus.SUCCEEDED: frozenset(),
    ToolExecutionStatus.FAILED: frozenset(),
    ToolExecutionStatus.TIMED_OUT: frozenset(),
    ToolExecutionStatus.CANCELLED: frozenset(),
    ToolExecutionStatus.BLOCKED_BY_POLICY: frozenset(),
    ToolExecutionStatus.APPROVAL_TERMINATED: frozenset(),
}


class ToolDefinition(BaseModel):
    key = models.CharField(max_length=128, unique=True)
    display_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=ToolDefinitionStatus.choices, default=ToolDefinitionStatus.ACTIVE
    )
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.LOW)
    side_effect_type = models.CharField(
        max_length=20, choices=SideEffectType.choices, default=SideEffectType.NONE
    )
    # References a server-owned ``tools.registry`` entry by its stable key —
    # never a Python import path, module, or callable name (section 13).
    handler_key = models.CharField(max_length=128)
    default_timeout_seconds = models.PositiveIntegerField(default=5)
    max_timeout_seconds = models.PositiveIntegerField(default=10)
    max_retries = models.PositiveIntegerField(default=0)
    idempotency_mode = models.CharField(
        max_length=20, choices=IdempotencyMode.choices, default=IdempotencyMode.SAFE
    )

    class Meta:
        ordering = ["key"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(key=""), name="tool_def_key_not_blank"),
            models.CheckConstraint(
                condition=models.Q(default_timeout_seconds__gt=0)
                & models.Q(max_timeout_seconds__gt=0),
                name="tool_def_timeouts_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.key

    @property
    def enabled(self) -> bool:
        return self.status == ToolDefinitionStatus.ACTIVE


class ToolBinding(BaseModel):
    """Which tools one immutable, published-or-draft ``AgentVersion`` may
    request. Bound to ``AgentVersion`` (not the mutable ``AgentDefinition``)
    so a published version's tool surface never silently changes underfoot
    (section 21-22)."""

    agent_version = models.ForeignKey(
        "agents.AgentVersion", on_delete=models.CASCADE, related_name="tool_bindings"
    )
    tool_definition = models.ForeignKey(
        ToolDefinition, on_delete=models.PROTECT, related_name="bindings"
    )
    enabled = models.BooleanField(default=True)
    configuration = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["agent_version", "tool_definition"],
                name="tool_binding_version_tool_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["agent_version", "enabled"], name="tool_binding_ver_enabled_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.agent_version_id}:{self.tool_definition_id}"


class ToolExecution(BaseModel):
    """One logical tool invocation. Never stores hidden reasoning or raw
    secrets — ``arguments_redacted``/``result_redacted`` are redacted before
    being written (section 24, 51-52)."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="tool_executions"
    )
    agent_run = models.ForeignKey(
        "agents.AgentRun", on_delete=models.CASCADE, related_name="tool_executions"
    )
    agent_version = models.ForeignKey(
        "agents.AgentVersion", on_delete=models.PROTECT, related_name="tool_executions"
    )
    tool_definition = models.ForeignKey(
        ToolDefinition, on_delete=models.PROTECT, related_name="executions"
    )
    tool_binding = models.ForeignKey(
        ToolBinding, on_delete=models.PROTECT, related_name="executions"
    )
    status = models.CharField(
        max_length=20, choices=ToolExecutionStatus.choices, default=ToolExecutionStatus.PENDING
    )

    idempotency_key = models.CharField(max_length=200, blank=True)
    arguments_fingerprint = models.CharField(max_length=64, blank=True)

    arguments_redacted = models.JSONField(default=dict, blank=True)
    result_redacted = models.JSONField(default=dict, blank=True)

    attempt_count = models.PositiveIntegerField(default=0)
    timeout_seconds = models.PositiveIntegerField()

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    error_code = models.CharField(max_length=64, blank=True)
    error_message_safe = models.CharField(max_length=500, blank=True)

    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(attempt_count__gte=0), name="tool_exec_attempt_gte_0"
            ),
            models.CheckConstraint(
                condition=models.Q(timeout_seconds__gt=0), name="tool_exec_timeout_gt_0"
            ),
            # Idempotency scope: workspace + tool + key. A blank key opts a
            # request out of idempotency entirely (no uniqueness enforced),
            # so the condition excludes blank keys from the constraint.
            models.UniqueConstraint(
                fields=["workspace", "tool_definition", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="tool_exec_idempotency_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="tool_exec_ws_created_idx"),
            models.Index(fields=["workspace", "status"], name="tool_exec_ws_status_idx"),
            models.Index(fields=["agent_run", "-created_at"], name="tool_exec_run_created_idx"),
            models.Index(
                fields=["tool_definition", "-created_at"], name="tool_exec_tool_created_idx"
            ),
        ]

    def clean(self) -> None:
        if self.agent_run_id and self.workspace_id != self.agent_run.workspace_id:
            raise ValidationError({"agent_run": "Execution must belong to the run's workspace."})

    def __str__(self) -> str:
        return f"{self.id}:{self.tool_definition_id}:{self.status}"
