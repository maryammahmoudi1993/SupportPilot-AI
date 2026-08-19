"""Human-approval domain models (Phase 8).

An ``ApprovalRequest`` is a one-per-``ToolExecution`` record — Phase 6's
existing idempotency claim on ``ToolExecution`` already guarantees "same
logical action" identity, so approval spam for repeated model/tool attempts
is prevented for free by the ``OneToOneField`` below (section 11), rather
than a second dedup mechanism.

An ``ApprovalDecision`` is a one-per-``ApprovalRequest`` immutable record —
"at most one final decision" is a database uniqueness constraint
(``OneToOneField``), not just an application-level check (section 41).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from common.models import BaseModel

MAX_SUMMARY_LENGTH = 500
MAX_COMMENT_LENGTH = 1000


class ApprovalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


APPROVAL_TERMINAL_STATUSES = frozenset(
    {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.CANCELLED,
    }
)


class ApprovalDecisionValue(models.TextChoices):
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"


class ApprovalRequest(BaseModel):
    """One pending-or-resolved human decision gating exactly one
    ``ToolExecution``. Never stores credentials, provider payloads, or
    hidden model reasoning — only safe, structured decision context
    (section 38, 52-53, 132-135)."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="approval_requests"
    )
    tool_execution = models.OneToOneField(
        "tools.ToolExecution", on_delete=models.CASCADE, related_name="approval_request"
    )
    policy_evaluation = models.OneToOneField(
        "policies.PolicyEvaluation", on_delete=models.CASCADE, related_name="approval_request"
    )
    risk_assessment = models.ForeignKey(
        "policies.RiskAssessment", on_delete=models.PROTECT, related_name="approval_requests"
    )

    status = models.CharField(
        max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )

    # The human who triggered the underlying AgentRun, if any — used only to
    # enforce the self-approval prohibition (section 49). Never the source
    # of authorization itself.
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests_requested",
    )
    # Server-derived minimum workspace role able to decide this request
    # (section 47-48) — never client-suppliable.
    required_role = models.CharField(max_length=32)

    summary = models.CharField(max_length=MAX_SUMMARY_LENGTH)
    # Safe, redacted structured context for a human decision (section 52-53,
    # 132-135) — reuses the same redaction as ``ToolExecution.arguments_redacted``.
    safe_context = models.JSONField(default=dict, blank=True)
    # Copy of the gated ToolExecution's arguments fingerprint, so a resume
    # attempt can prove "approved action == executed action" even if read
    # independently of the ToolExecution row (section 53-55).
    arguments_fingerprint = models.CharField(max_length=64, blank=True)

    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")),
                name="approval_expires_after_created",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "status", "created_at"], name="approval_ws_status_idx"
            ),
            models.Index(fields=["workspace", "expires_at"], name="approval_ws_expires_idx"),
            models.Index(fields=["required_role", "status"], name="approval_role_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.id}:{self.status}"


class ApprovalDecision(BaseModel):
    """An immutable human decision on one ``ApprovalRequest``. The
    ``OneToOneField`` is the database-enforced "exactly one final decision"
    invariant (section 41-42) — a second ``create()`` for the same request
    raises ``IntegrityError`` regardless of application-level races."""

    approval_request = models.OneToOneField(
        ApprovalRequest, on_delete=models.CASCADE, related_name="decision"
    )
    decision = models.CharField(max_length=10, choices=ApprovalDecisionValue.choices)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="approval_decisions",
    )
    safe_comment = models.CharField(max_length=MAX_COMMENT_LENGTH, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.approval_request_id}:{self.decision}"
