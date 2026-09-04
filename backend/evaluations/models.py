"""Evaluation datasets, cases, runs, and per-case results.

Reproducibility strategy (section 16, 45): datasets/cases stay simple and
mutable; ``EvaluationRun`` creation snapshots every case it will execute into
an immutable ``EvaluationCaseSnapshot`` row. A run's meaning can never change
because someone edited a case after the run was created — the run only ever
reads its own snapshots.

No hidden reasoning is ever persisted here (section 50) — only structured,
safe scorer output derived from the real ``AgentRun``/``AgentStep``/
``ToolExecution``/``ApprovalRequest`` records it references.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from common.models import BaseModel


class EvaluationDatasetStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class EvaluationCaseStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DISABLED = "disabled", "Disabled"


class EvaluationRunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


EVALUATION_RUN_TERMINAL_STATUSES = frozenset(
    {
        EvaluationRunStatus.SUCCEEDED,
        EvaluationRunStatus.PARTIAL,
        EvaluationRunStatus.FAILED,
        EvaluationRunStatus.CANCELLED,
    }
)

EVALUATION_RUN_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    EvaluationRunStatus.PENDING: frozenset(
        {EvaluationRunStatus.RUNNING, EvaluationRunStatus.CANCELLED, EvaluationRunStatus.FAILED}
    ),
    EvaluationRunStatus.RUNNING: frozenset(
        {
            EvaluationRunStatus.SUCCEEDED,
            EvaluationRunStatus.PARTIAL,
            EvaluationRunStatus.FAILED,
            EvaluationRunStatus.CANCELLED,
        }
    ),
    EvaluationRunStatus.SUCCEEDED: frozenset(),
    EvaluationRunStatus.PARTIAL: frozenset(),
    EvaluationRunStatus.FAILED: frozenset(),
    EvaluationRunStatus.CANCELLED: frozenset(),
}


class EvaluationResultStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


EVALUATION_RESULT_TERMINAL_STATUSES = frozenset(
    {
        EvaluationResultStatus.SUCCEEDED,
        EvaluationResultStatus.FAILED,
        EvaluationResultStatus.CANCELLED,
    }
)

EVALUATION_RESULT_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    EvaluationResultStatus.PENDING: frozenset(
        {EvaluationResultStatus.RUNNING, EvaluationResultStatus.CANCELLED}
    ),
    EvaluationResultStatus.RUNNING: frozenset(
        {EvaluationResultStatus.SUCCEEDED, EvaluationResultStatus.FAILED}
    ),
    EvaluationResultStatus.SUCCEEDED: frozenset(),
    EvaluationResultStatus.FAILED: frozenset(),
    EvaluationResultStatus.CANCELLED: frozenset(),
}


class EvaluationProviderMode(models.TextChoices):
    # Phase 12 only ships the deterministic offline path (section 14, 67);
    # a LIVE mode is an explicit future opt-in, never selected by default.
    DETERMINISTIC = "deterministic", "Deterministic (offline)"


#: Bounded, stable failure taxonomy (section 49) — never raw external
#: exception text.
class EvaluationFailureCode(models.TextChoices):
    INVALID_CASE = "invalid_case", "Invalid case"
    AGENT_EXECUTION_FAILED = "agent_execution_failed", "Agent execution failed"
    BUDGET_EXCEEDED = "budget_exceeded", "Budget exceeded"
    PROVIDER_FAILURE = "provider_failure", "Provider failure"
    FORBIDDEN_TOOL_VIOLATION = "forbidden_tool_violation", "Forbidden tool violation"
    POLICY_VIOLATION = "policy_violation", "Policy violation"
    APPROVAL_VIOLATION = "approval_violation", "Approval violation"
    OUTCOME_MISMATCH = "outcome_mismatch", "Outcome mismatch"
    SCORING_FAILED = "scoring_failed", "Scoring failed"
    CANCELLED = "cancelled", "Cancelled"
    # Phase 16 Checkpoint 2 Part C: assigned only by
    # ``evaluations.recovery.recover_stuck_evaluation_runs`` to a case whose
    # worker crashed mid-execution and never reached a terminal state —
    # never assigned by normal case-execution failure handling.
    WORKER_CRASH_RECOVERED = "worker_crash_recovered", "Worker crash recovered"


class EvaluationDataset(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="evaluation_datasets"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=EvaluationDatasetStatus.choices,
        default=EvaluationDatasetStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="evaluation_datasets_created",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(name=""), name="eval_dataset_name_not_blank"
            ),
            models.UniqueConstraint(
                fields=["workspace", "name"], name="eval_dataset_workspace_name_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"], name="eval_dataset_ws_status_idx"),
            models.Index(fields=["workspace", "-created_at"], name="eval_dataset_ws_created_idx"),
        ]

    def __str__(self) -> str:
        return self.name


class EvaluationCase(BaseModel):
    dataset = models.ForeignKey(EvaluationDataset, on_delete=models.CASCADE, related_name="cases")
    key = models.SlugField(max_length=128)
    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20, choices=EvaluationCaseStatus.choices, default=EvaluationCaseStatus.ACTIVE
    )
    input_message = models.TextField()
    # Validated against ``evaluations.schemas.EvaluationSeededContext`` /
    # ``EvaluationCaseExpectations`` before save (section 17-19) — never
    # arbitrary executable content (section 17).
    seeded_context = models.JSONField(default=dict, blank=True)
    expectations = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="evaluation_cases_created",
    )

    class Meta:
        ordering = ["dataset_id", "key"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "key"], name="eval_case_dataset_key_uniq"),
        ]
        indexes = [
            models.Index(fields=["dataset", "status"], name="eval_case_dataset_status_idx"),
        ]

    def clean(self) -> None:
        # Never store an unvalidated seeded_context/expectations shape
        # (section 17-19) — a Pydantic ``ValidationError`` here is
        # translated into the normal Django validation-error surface so it
        # reaches callers the same way any other field validation does.
        from pydantic import ValidationError as PydanticValidationError

        from .schemas import validate_case_expectations, validate_seeded_context

        try:
            self.seeded_context = validate_seeded_context(self.seeded_context or {})
        except PydanticValidationError as exc:
            raise ValidationError({"seeded_context": str(exc)}) from exc
        try:
            self.expectations = validate_case_expectations(self.expectations or {})
        except PydanticValidationError as exc:
            raise ValidationError({"expectations": str(exc)}) from exc

    def __str__(self) -> str:
        return f"{self.dataset_id}:{self.key}"


class EvaluationRun(BaseModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="evaluation_runs"
    )
    dataset = models.ForeignKey(EvaluationDataset, on_delete=models.PROTECT, related_name="runs")
    agent_version = models.ForeignKey(
        "agents.AgentVersion", on_delete=models.PROTECT, related_name="evaluation_runs"
    )
    status = models.CharField(
        max_length=20, choices=EvaluationRunStatus.choices, default=EvaluationRunStatus.PENDING
    )
    provider_mode = models.CharField(
        max_length=20,
        choices=EvaluationProviderMode.choices,
        default=EvaluationProviderMode.DETERMINISTIC,
    )
    # Immutable snapshot of the regression-threshold configuration this run
    # was gated against (section 20, 31) — never re-read from mutable
    # current settings after the run starts.
    threshold_config = models.JSONField(default=dict, blank=True)

    total_cases = models.PositiveIntegerField(default=0)
    completed_cases = models.PositiveIntegerField(default=0)
    passed_cases = models.PositiveIntegerField(default=0)
    failed_cases = models.PositiveIntegerField(default=0)

    correlation_id = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="evaluation_runs_created",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(completed_cases__lte=models.F("total_cases")),
                name="eval_run_completed_lte_total",
            ),
            models.CheckConstraint(
                condition=models.Q(passed_cases__lte=models.F("completed_cases")),
                name="eval_run_passed_lte_completed",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"], name="eval_run_ws_status_idx"),
            models.Index(fields=["workspace", "-created_at"], name="eval_run_ws_created_idx"),
            models.Index(fields=["dataset", "-created_at"], name="eval_run_dataset_created_idx"),
            # Phase 16 Checkpoint 2 Part F: backs
            # ``evaluations.recovery.recover_stuck_evaluation_runs``'s sweep
            # query (``status=RUNNING, updated_at<=cutoff``), deliberately
            # global/cross-workspace like ``agents``' equivalent index.
            # Measured with ``EXPLAIN ANALYZE`` against 150k synthetic rows:
            # a full parallel sequential scan (~18ms, ~6,400 buffer reads)
            # before this index vs. an index scan (~0.13ms, ~104 buffer
            # reads) after it.
            models.Index(fields=["status", "updated_at"], name="eval_run_status_updated_idx"),
        ]

    def clean(self) -> None:
        if self.dataset_id and self.workspace_id != self.dataset.workspace_id:
            raise ValidationError({"dataset": "Dataset must belong to the run workspace."})

    def __str__(self) -> str:
        return f"{self.id}:{self.status}"


class EvaluationCaseSnapshot(BaseModel):
    """Immutable copy of one case's content at the moment its run was
    created (section 16, 45). ``case`` is kept only for traceability and may
    become null if the source case is later deleted — the snapshot's own
    columns remain the authoritative content for anything already executed."""

    run = models.ForeignKey(EvaluationRun, on_delete=models.CASCADE, related_name="case_snapshots")
    case = models.ForeignKey(
        EvaluationCase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="snapshots",
    )
    sequence = models.PositiveIntegerField()
    case_key = models.CharField(max_length=128)
    name = models.CharField(max_length=200)
    input_message = models.TextField()
    seeded_context = models.JSONField(default=dict, blank=True)
    expectations = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["run_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"], name="eval_case_snap_run_sequence_uniq"
            ),
            models.UniqueConstraint(
                fields=["run", "case_key"], name="eval_case_snap_run_case_key_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["run"], name="eval_case_snap_run_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.case_key}"


class EvaluationResult(BaseModel):
    """One case execution's outcome.

    The *initial* (non-replay) result per snapshot is a database invariant
    — enforced by ``eval_result_one_initial_per_snapshot`` below, a partial
    unique constraint on ``case_snapshot`` where ``replay_of`` is null
    (section 21, 46) — pre-created ``PENDING`` alongside the snapshot so a
    worker only ever claims that existing row (never creates a second one)
    regardless of task redelivery (section 23, 59). A *replay* (section 33)
    always creates a new, additional result referencing the same snapshot
    via ``replay_of``, which is why this is a plain ``ForeignKey`` rather
    than a ``OneToOneField``."""

    run = models.ForeignKey(EvaluationRun, on_delete=models.CASCADE, related_name="results")
    case_snapshot = models.ForeignKey(
        EvaluationCaseSnapshot, on_delete=models.CASCADE, related_name="results"
    )
    status = models.CharField(
        max_length=20,
        choices=EvaluationResultStatus.choices,
        default=EvaluationResultStatus.PENDING,
    )
    agent_run = models.ForeignKey(
        "agents.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluation_results",
    )
    # Structured, safe scorer output — validated against
    # ``evaluations.schemas.EvaluationScorerOutput``. Never hidden reasoning
    # (section 50).
    scorer_output = models.JSONField(default=dict, blank=True)
    passed = models.BooleanField(null=True)
    failure_code = models.CharField(
        max_length=32, choices=EvaluationFailureCode.choices, blank=True
    )
    failure_message_safe = models.CharField(max_length=500, blank=True)

    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # Replay lineage (section 33) — a replay always creates a new result and
    # never mutates the historical one it replays.
    replay_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replays",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["case_snapshot"],
                condition=models.Q(replay_of__isnull=True),
                name="eval_result_one_initial_per_snapshot",
            ),
        ]
        indexes = [
            models.Index(fields=["run", "status"], name="eval_result_run_status_idx"),
            models.Index(fields=["run", "passed"], name="eval_result_run_passed_idx"),
            models.Index(fields=["case_snapshot"], name="eval_result_case_snap_idx"),
        ]

    def clean(self) -> None:
        if self.case_snapshot_id and self.run_id != self.case_snapshot.run_id:
            raise ValidationError(
                {"case_snapshot": "Result must belong to the snapshot's own run."}
            )

    def __str__(self) -> str:
        return f"{self.id}:{self.status}"
