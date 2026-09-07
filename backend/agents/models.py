"""Tenant-owned agent configuration, run, and safe execution-trace models.

No hidden chain-of-thought is ever persisted here — ``AgentStep`` stores only
safe, structured operational facts (step type, provider/model, token counts,
latency, safe error codes). See ``docs/adr`` for the rationale.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from common.models import BaseModel


class AgentDefinitionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    ARCHIVED = "archived", "Archived"


class AgentVersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    RETIRED = "retired", "Retired"


class AgentProvider(models.TextChoices):
    FAKE = "fake", "Deterministic fake"
    OPENAI = "openai", "OpenAI"


class AgentRunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    BUDGET_EXCEEDED = "budget_exceeded", "Budget exceeded"
    # Phase 8: the run's one bounded tool round-trip was gated by policy and
    # is paused pending a human decision. Deliberately non-terminal and
    # excluded from busy-waiting (section 57-58) — nothing holds a worker
    # thread, Celery worker, or DB transaction open while a run sits here.
    WAITING_FOR_APPROVAL = "waiting_for_approval", "Waiting for approval"
    # Phase 9 Block 5: orchestration deliberately transferred responsibility
    # to a human operator (section 4, 17-19) — a successful escalation
    # outcome, never a failure. Terminal: no further LLM call, tool call, or
    # provider side effect may occur for this run once here.
    HANDED_OFF = "handed_off", "Handed off to a human"


AGENT_RUN_TERMINAL_STATUSES = frozenset(
    {
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.BUDGET_EXCEEDED,
        AgentRunStatus.HANDED_OFF,
    }
)


class AgentRunTrigger(models.TextChoices):
    MANUAL = "manual", "Manual"
    CONVERSATION = "conversation", "Conversation"
    TICKET = "ticket", "Ticket"
    API = "api", "API"
    # Phase 12: a run started by the evaluation harness against a seeded,
    # deterministic case rather than a real conversation/ticket/API caller.
    EVALUATION = "evaluation", "Evaluation"


class AgentStepType(models.TextChoices):
    RUN_STARTED = "run_started", "Run started"
    REQUEST_NORMALIZED = "request_normalized", "Request normalized"
    BUDGET_CHECKED = "budget_checked", "Budget checked"
    PROVIDER_CALL_STARTED = "provider_call_started", "Provider call started"
    PROVIDER_CALL_SUCCEEDED = "provider_call_succeeded", "Provider call succeeded"
    PROVIDER_CALL_FAILED = "provider_call_failed", "Provider call failed"
    RESPONSE_FINALIZED = "response_finalized", "Response finalized"
    RUN_COMPLETED = "run_completed", "Run completed"
    RUN_FAILED = "run_failed", "Run failed"
    RUN_CANCELLED = "run_cancelled", "Run cancelled"
    TOOL_REQUESTED = "tool_requested", "Tool requested"
    TOOL_VALIDATION_FAILED = "tool_validation_failed", "Tool validation failed"
    TOOL_EXECUTION_STARTED = "tool_execution_started", "Tool execution started"
    TOOL_EXECUTION_SUCCEEDED = "tool_execution_succeeded", "Tool execution succeeded"
    TOOL_EXECUTION_FAILED = "tool_execution_failed", "Tool execution failed"
    TOOL_EXECUTION_TIMED_OUT = "tool_execution_timed_out", "Tool execution timed out"
    TOOL_IDEMPOTENCY_REUSED = "tool_idempotency_reused", "Tool idempotency reused"
    # Phase 8: safe, structured policy/approval trace events. Never hidden
    # chain-of-thought — only operational facts (section 85).
    RISK_ASSESSED = "risk_assessed", "Risk assessed"
    POLICY_EVALUATED = "policy_evaluated", "Policy evaluated"
    APPROVAL_REQUESTED = "approval_requested", "Approval requested"
    APPROVAL_APPROVED = "approval_approved", "Approval approved"
    APPROVAL_REJECTED = "approval_rejected", "Approval rejected"
    APPROVAL_EXPIRED = "approval_expired", "Approval expired"
    RUN_WAITING_FOR_APPROVAL = "run_waiting_for_approval", "Run waiting for approval"
    EXECUTION_RESUMED = "execution_resumed", "Execution resumed"
    # Phase 9 Block 5: safe, structured handoff trace events (section 62) —
    # never hidden chain-of-thought, only the operational fact that a
    # handoff was requested/completed.
    HANDOFF_REQUESTED = "handoff_requested", "Handoff requested"
    RUN_HANDED_OFF = "run_handed_off", "Run handed off"


class AgentStepStatus(models.TextChoices):
    STARTED = "started", "Started"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class AgentDefinition(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="agent_definitions"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=AgentDefinitionStatus.choices, default=AgentDefinitionStatus.ACTIVE
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="agent_definitions_created",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(name=""), name="agent_def_name_not_blank"),
            models.UniqueConstraint(
                fields=["workspace", "name"], name="agent_def_workspace_name_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"], name="agent_def_workspace_status_idx"),
            models.Index(fields=["workspace", "-created_at"], name="agent_def_ws_created_idx"),
        ]

    def save(self, *args, **kwargs) -> None:
        self.name = " ".join(self.name.split())
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class AgentVersion(BaseModel):
    agent_definition = models.ForeignKey(
        AgentDefinition, on_delete=models.CASCADE, related_name="versions"
    )
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=AgentVersionStatus.choices, default=AgentVersionStatus.DRAFT
    )
    system_prompt = models.TextField(blank=True)
    provider = models.CharField(max_length=32, choices=AgentProvider.choices)
    model = models.CharField(max_length=128)
    temperature = models.FloatField(default=0.0)
    max_output_tokens = models.PositiveIntegerField(default=512)

    # Bounded execution budgets (Phase 5 section 21-22).
    max_model_calls = models.PositiveIntegerField(default=1)
    max_steps = models.PositiveIntegerField(default=20)
    wall_time_limit_seconds = models.PositiveIntegerField(default=30)
    provider_timeout_seconds = models.PositiveIntegerField(default=30)
    max_total_tokens = models.PositiveIntegerField(null=True, blank=True)
    max_estimated_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    max_retry_attempts = models.PositiveIntegerField(default=1)

    # Bounds how many distinct tool-call round-trips one run may take
    # (section 41 of the Phase 6 brief). A dedicated counter — rather than
    # overloading ``max_steps`` — because a tool round-trip is a distinct,
    # policy-relevant unit from a generic trace step.
    max_tool_calls = models.PositiveIntegerField(default=3)

    runtime_config = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="agent_versions_created",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["agent_definition", "version"], name="agent_ver_definition_version_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(max_model_calls__gte=1), name="agent_ver_max_calls_gte_1"
            ),
        ]
        indexes = [
            models.Index(fields=["agent_definition", "status"], name="agent_ver_def_status_idx"),
        ]

    def clean(self) -> None:
        if self.model.strip() == "":
            raise ValidationError({"model": "Model must not be blank."})

    def __str__(self) -> str:
        return f"{self.agent_definition_id}:v{self.version}"


class AgentRun(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="agent_runs"
    )
    agent_version = models.ForeignKey(AgentVersion, on_delete=models.PROTECT, related_name="runs")
    conversation = models.ForeignKey(
        "conversations.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )
    # Phase 9 (section 17-19): the customer message that triggered this run,
    # if any. A ``OneToOneField`` is the run-idempotency invariant itself —
    # "one logical AgentRun per triggering message" is a database uniqueness
    # constraint, not just an application-level check, so a duplicate
    # HTTP/worker/webhook redelivery of the same message can never spawn a
    # second run (see ``agents.orchestration.start_support_agent_run``).
    trigger_message = models.OneToOneField(
        "conversations.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_run",
    )
    # Phase 9 (section 56): the assistant-facing Message this run's final
    # response was persisted as, if any. A ``OneToOneField`` makes "at most
    # one final message per run" a database invariant, so a worker retry
    # after the response was generated but before completion was
    # acknowledged can never create a duplicate customer-visible message.
    output_message = models.OneToOneField(
        "conversations.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_run_output",
    )
    trigger = models.CharField(
        max_length=20, choices=AgentRunTrigger.choices, default=AgentRunTrigger.MANUAL
    )
    status = models.CharField(
        max_length=20, choices=AgentRunStatus.choices, default=AgentRunStatus.PENDING
    )
    input_message = models.TextField()
    input_metadata = models.JSONField(default=dict, blank=True)
    final_response = models.TextField(blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    failure_code = models.CharField(max_length=64, blank=True)
    failure_message_safe = models.CharField(max_length=255, blank=True)

    model_call_count = models.PositiveIntegerField(default=0)
    step_count = models.PositiveIntegerField(default=0)
    tool_call_count = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    correlation_id = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="agent_runs_created",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status"], name="agent_run_workspace_status_idx"),
            models.Index(fields=["workspace", "-created_at"], name="agent_run_ws_created_idx"),
            models.Index(fields=["agent_version"], name="agent_run_agent_version_idx"),
            # Phase 16 Checkpoint 2 Part F: backs
            # ``agents.recovery.recover_stuck_agent_runs``'s sweep query
            # (``status=RUNNING, updated_at<=cutoff``), which is
            # deliberately global/cross-workspace — the existing
            # ``(workspace, status)`` index can't serve a query that never
            # filters on workspace. Measured with ``EXPLAIN ANALYZE`` against
            # 308k synthetic rows: a full parallel sequential scan (~27ms,
            # ~11,900 buffer reads) before this index vs. an index scan
            # (~0.2ms, ~103 buffer reads) after it.
            models.Index(fields=["status", "updated_at"], name="agent_run_status_updated_idx"),
        ]

    def clean(self) -> None:
        if (
            self.agent_version_id
            and self.workspace_id != self.agent_version.agent_definition.workspace_id
        ):
            raise ValidationError(
                {"agent_version": "Agent version must belong to the run workspace."}
            )
        trigger_message = self.trigger_message
        if trigger_message is not None and trigger_message.workspace_id != self.workspace_id:
            raise ValidationError(
                {"trigger_message": "Trigger message must belong to the run workspace."}
            )
        output_message = self.output_message
        if output_message is not None and output_message.workspace_id != self.workspace_id:
            raise ValidationError(
                {"output_message": "Output message must belong to the run workspace."}
            )

    def __str__(self) -> str:
        return f"{self.id}:{self.status}"


class AgentStep(BaseModel):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="agent_steps"
    )
    sequence = models.PositiveIntegerField()
    step_type = models.CharField(max_length=32, choices=AgentStepType.choices)
    status = models.CharField(
        max_length=20, choices=AgentStepStatus.choices, default=AgentStepStatus.SUCCEEDED
    )
    provider = models.CharField(max_length=32, blank=True)
    model = models.CharField(max_length=128, blank=True)
    input_summary = models.CharField(max_length=500, blank=True)
    output_summary = models.CharField(max_length=500, blank=True)
    safe_metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["run_id", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["run", "sequence"], name="agent_step_run_sequence_uniq")
        ]
        indexes = [
            models.Index(fields=["workspace", "run"], name="agent_step_workspace_run_idx"),
        ]

    def clean(self) -> None:
        if self.run_id and self.workspace_id != self.run.workspace_id:
            raise ValidationError({"run": "Step must belong to the run workspace."})

    def __str__(self) -> str:
        return f"{self.run_id}#{self.sequence}:{self.step_type}"
