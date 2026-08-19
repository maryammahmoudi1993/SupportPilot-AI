"""Deterministic, workspace-scoped policy domain models (Phase 8).

``Policy`` -> ``PolicyVersion`` -> ``PolicyRule`` is an immutable-once-active
chain: a published/active ``PolicyVersion``'s rules are frozen forever (see
``docs/architecture/policy-approval-engine.md``). Changing policy behavior
means creating a new ``PolicyVersion``, never mutating an active one — that
is what lets a historical ``PolicyEvaluation`` stay reproducible.

Nothing in this module stores executable code. ``PolicyRule.condition_config``
is a small, declarative JSON document interpreted only by the trusted
predicate registry in ``policies/predicates.py`` — never ``eval``/``exec``,
never a dynamic import.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from common.models import BaseModel
from tools.contracts import RiskLevel, SideEffectType


class PolicyStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    ARCHIVED = "archived", "Archived"


class PolicyVersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    SUPERSEDED = "superseded", "Superseded"


class PolicyEffect(models.TextChoices):
    """The only three normalized outcomes a policy evaluation may produce
    (section 7 of the Phase 8 brief). No ambiguous/soft states."""

    ALLOW = "allow", "Allow"
    DENY = "deny", "Deny"
    REQUIRE_APPROVAL = "require_approval", "Require approval"


# Safe precedence when more than one enabled rule matches the same action
# (section 16): a single DENY anywhere always wins, then REQUIRE_APPROVAL,
# and only ALLOW if every matched rule allows. This is a fixed, code-owned
# choice — not configurable per policy — because "deny wins" is the only
# direction that can never be weakened by rule ordering mistakes.
POLICY_EFFECT_PRECEDENCE: tuple[str, ...] = (
    PolicyEffect.DENY,
    PolicyEffect.REQUIRE_APPROVAL,
    PolicyEffect.ALLOW,
)

MAX_POLICY_NAME_LENGTH = 200
MAX_POLICY_DESCRIPTION_LENGTH = 2000
MAX_RULE_NAME_LENGTH = 200
MAX_SAFE_REASON_LENGTH = 500
MAX_RULES_PER_VERSION = 50


class Policy(BaseModel):
    """A workspace-owned, named policy configuration. At most one policy per
    workspace may be ``active`` at a time (section 120-121) — that single
    active policy's active version governs every tool-action evaluation for
    the workspace."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="policies"
    )
    name = models.CharField(max_length=MAX_POLICY_NAME_LENGTH)
    description = models.CharField(max_length=MAX_POLICY_DESCRIPTION_LENGTH, blank=True)
    status = models.CharField(
        max_length=20, choices=PolicyStatus.choices, default=PolicyStatus.DRAFT
    )
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="policies_created"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(name=""), name="policy_name_not_blank"),
            models.UniqueConstraint(
                fields=["workspace", "name"], name="policy_workspace_name_uniq"
            ),
            # System safety floor (section 120): a workspace can never have two
            # ambiguous active policies — activation is a transactional switch.
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(status=PolicyStatus.ACTIVE),
                name="policy_one_active_per_workspace",
            ),
        ]
        indexes = [models.Index(fields=["workspace", "status"], name="policy_ws_status_idx")]

    def __str__(self) -> str:
        return f"{self.name} ({self.workspace_id})"


class PolicyVersion(BaseModel):
    """An immutable-once-active snapshot of a policy's rule set. Historical
    ``PolicyEvaluation`` rows reference the exact version that was active at
    evaluation time (section 14, 118-119) — activating a new version never
    rewrites what an already-evaluated action was judged against."""

    policy = models.ForeignKey(Policy, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=PolicyVersionStatus.choices, default=PolicyVersionStatus.DRAFT
    )
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="policy_versions_created",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "version"], name="policy_version_policy_version_uniq"
            ),
            # At most one active version per policy (section 14, 120).
            models.UniqueConstraint(
                fields=["policy"],
                condition=models.Q(status=PolicyVersionStatus.ACTIVE),
                name="policy_version_one_active_per_policy",
            ),
        ]
        indexes = [models.Index(fields=["policy", "status"], name="policy_ver_policy_status_idx")]

    def __str__(self) -> str:
        return f"{self.policy_id}:v{self.version}"


class PolicyRule(BaseModel):
    """One declarative rule within an immutable ``PolicyVersion``. Rules are
    never executable code — ``condition_config`` is interpreted only by the
    trusted predicate registry (section 18-20)."""

    policy_version = models.ForeignKey(
        PolicyVersion, on_delete=models.CASCADE, related_name="rules"
    )
    name = models.CharField(max_length=MAX_RULE_NAME_LENGTH)
    priority = models.PositiveIntegerField()
    enabled = models.BooleanField(default=True)

    # Blank = applies to every tool. A non-blank value must match the
    # ToolExecutionContext's resolved tool key exactly.
    tool_key = models.CharField(max_length=128, blank=True)
    # Empty list = any risk level / side-effect type matches.
    risk_levels = models.JSONField(default=list, blank=True)
    side_effect_types = models.JSONField(default=list, blank=True)

    # {"all": [{"predicate": "<registered name>", ...params}, ...]}. An
    # empty "all" list matches unconditionally (used for catch-all rules).
    condition_config = models.JSONField(default=dict, blank=True)

    effect = models.CharField(max_length=20, choices=PolicyEffect.choices)
    # Only meaningful when effect == REQUIRE_APPROVAL. Blank = derive the
    # required role from the action's effective risk level (section 48).
    required_role = models.CharField(max_length=32, blank=True)
    approval_ttl_seconds = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["priority", "id"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(name=""), name="policy_rule_name_not_blank"),
            models.UniqueConstraint(
                fields=["policy_version", "priority"], name="policy_rule_version_priority_uniq"
            ),
            models.UniqueConstraint(
                fields=["policy_version", "name"], name="policy_rule_version_name_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["policy_version", "enabled"], name="policy_rule_ver_enabled_idx"),
        ]

    def clean(self) -> None:
        for level in self.risk_levels or []:
            if level not in RiskLevel.values:
                raise ValidationError({"risk_levels": f"Unknown risk level: {level!r}."})
        for kind in self.side_effect_types or []:
            if kind not in SideEffectType.values:
                raise ValidationError({"side_effect_types": f"Unknown side-effect type: {kind!r}."})

    def __str__(self) -> str:
        return f"{self.policy_version_id}:{self.name}"


class RiskAssessment(BaseModel):
    """An immutable snapshot of one tool action's deterministic risk
    classification (section 21-24). Never recalculated in place — a new
    evaluation of the "same" action (e.g. a retried attempt) gets its own
    ``ToolExecution`` and therefore its own ``RiskAssessment``."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="risk_assessments"
    )
    tool_execution = models.OneToOneField(
        "tools.ToolExecution", on_delete=models.CASCADE, related_name="risk_assessment"
    )
    tool_key = models.CharField(max_length=128)
    base_risk = models.CharField(max_length=20, choices=RiskLevel.choices)
    effective_risk = models.CharField(max_length=20, choices=RiskLevel.choices)
    side_effect_type = models.CharField(max_length=20, choices=SideEffectType.choices)
    # Safe structured factors only (section 23) — never credentials, never
    # hidden model reasoning.
    factors = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["workspace", "-created_at"], name="risk_ws_created_idx")]

    def __str__(self) -> str:
        return f"{self.tool_execution_id}:{self.effective_risk}"


class PolicyEvaluation(BaseModel):
    """The immutable, persisted result of one deterministic policy
    evaluation (section 25). Exactly one per ``ToolExecution``."""

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="policy_evaluations"
    )
    tool_execution = models.OneToOneField(
        "tools.ToolExecution", on_delete=models.CASCADE, related_name="policy_evaluation"
    )
    risk_assessment = models.OneToOneField(
        RiskAssessment, on_delete=models.CASCADE, related_name="policy_evaluation"
    )
    # Null when no workspace policy is active and the code-owned system
    # default was applied (section 122-123).
    policy_version = models.ForeignKey(
        PolicyVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="evaluations"
    )
    decision = models.CharField(max_length=20, choices=PolicyEffect.choices)
    decision_code = models.CharField(max_length=64)
    safe_reason = models.CharField(max_length=MAX_SAFE_REASON_LENGTH)
    matched_rule_ids = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "-created_at"], name="policy_eval_ws_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.tool_execution_id}:{self.decision}"
