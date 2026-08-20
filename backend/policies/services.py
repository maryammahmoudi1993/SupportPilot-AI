"""Policy configuration services and the two persistence helpers the tool
execution gate uses (``persist_risk_assessment`` / ``persist_policy_evaluation``).

Policy configuration mutation (create/version/rule/activate) is privileged —
callers are validated at the API layer (``CanManagePolicies``); this module
assumes an already-authorized ``actor``.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from accounts.models import User
from audit.models import AuditAction
from audit.services import record_event
from workspaces.models import Workspace

from .errors import (
    PolicyInvalidRuleError,
    PolicyLimitExceededError,
    PolicyVersionNotActivatableError,
)
from .models import (
    MAX_RULES_PER_VERSION,
    Policy,
    PolicyEvaluation,
    PolicyRule,
    PolicyStatus,
    PolicyVersion,
    PolicyVersionStatus,
    RiskAssessment,
)
from .predicates import known_predicate_names
from .risk import RiskOutcome

# ---------------------------------------------------------------------------
# Gate persistence — called only from tools.execution's policy gate.
# ---------------------------------------------------------------------------


def persist_risk_assessment(*, execution, risk: RiskOutcome) -> RiskAssessment:
    return RiskAssessment.objects.create(
        workspace=execution.workspace,
        tool_execution=execution,
        tool_key=execution.tool_definition.key,
        base_risk=risk.base_risk,
        effective_risk=risk.effective_risk,
        side_effect_type=risk.side_effect_type,
        factors=risk.factors,
    )


def persist_policy_evaluation(
    *,
    execution,
    risk_assessment: RiskAssessment,
    policy_version: PolicyVersion | None,
    decision: str,
    decision_code: str,
    safe_reason: str,
    matched_rule_ids: list[str],
) -> PolicyEvaluation:
    return PolicyEvaluation.objects.create(
        workspace=execution.workspace,
        tool_execution=execution,
        risk_assessment=risk_assessment,
        policy_version=policy_version,
        decision=decision,
        decision_code=decision_code,
        safe_reason=safe_reason[:500],
        matched_rule_ids=matched_rule_ids,
    )


# ---------------------------------------------------------------------------
# Policy configuration management (API-facing)
# ---------------------------------------------------------------------------


def create_policy(
    *,
    workspace: Workspace,
    actor: User,
    name: str,
    description: str = "",
    request_id: str | None = None,
) -> Policy:
    with transaction.atomic():
        policy = Policy.objects.create(
            workspace=workspace, name=name.strip(), description=description, created_by=actor
        )
        record_event(
            action=AuditAction.POLICY_CREATED,
            target_type="policy",
            target_id=policy.id,
            actor=actor,
            workspace=workspace,
            metadata={"policy_id": str(policy.id), "name": policy.name},
            request_id=request_id,
        )
    return policy


def update_policy(
    *,
    workspace: Workspace,
    policy: Policy,
    actor: User,
    name: str | None = None,
    description: str | None = None,
    request_id: str | None = None,
) -> Policy:
    with transaction.atomic():
        if name is not None:
            policy.name = name.strip()
        if description is not None:
            policy.description = description
        policy.save()
        record_event(
            action=AuditAction.POLICY_UPDATED,
            target_type="policy",
            target_id=policy.id,
            actor=actor,
            workspace=workspace,
            metadata={"policy_id": str(policy.id)},
            request_id=request_id,
        )
    return policy


def create_policy_version(
    *, workspace: Workspace, policy: Policy, actor: User, request_id: str | None = None
) -> PolicyVersion:
    with transaction.atomic():
        last = (
            PolicyVersion.objects.select_for_update()
            .filter(policy=policy)
            .order_by("-version")
            .first()
        )
        next_version = (last.version + 1) if last else 1
        version = PolicyVersion.objects.create(
            policy=policy, version=next_version, created_by=actor
        )
        record_event(
            action=AuditAction.POLICY_VERSION_CREATED,
            target_type="policy_version",
            target_id=version.id,
            actor=actor,
            workspace=workspace,
            metadata={"policy_id": str(policy.id), "version": version.version},
            request_id=request_id,
        )
    return version


def add_policy_rule(
    *, workspace: Workspace, policy_version: PolicyVersion, actor: User, data: dict[str, Any]
) -> PolicyRule:
    if policy_version.status != PolicyVersionStatus.DRAFT:
        raise PolicyInvalidRuleError("Rules can only be added to a draft policy version.")
    current_count = PolicyRule.objects.filter(policy_version=policy_version).count()
    if current_count >= MAX_RULES_PER_VERSION:
        raise PolicyLimitExceededError(
            f"A policy version may not exceed {MAX_RULES_PER_VERSION} rules."
        )
    condition_config = data.get("condition_config") or {"all": []}
    _validate_condition_config(condition_config)
    with transaction.atomic():
        rule = PolicyRule.objects.create(
            policy_version=policy_version,
            name=data["name"].strip(),
            priority=data["priority"],
            enabled=data.get("enabled", True),
            tool_key=data.get("tool_key", ""),
            risk_levels=data.get("risk_levels", []),
            side_effect_types=data.get("side_effect_types", []),
            condition_config=condition_config,
            effect=data["effect"],
            required_role=data.get("required_role", ""),
            approval_ttl_seconds=data.get("approval_ttl_seconds"),
        )
        rule.full_clean()
    return rule


def _validate_condition_config(condition_config: dict[str, Any]) -> None:
    if not isinstance(condition_config, dict) or set(condition_config) - {"all"}:
        raise PolicyInvalidRuleError("condition_config must be an object with only an 'all' key.")
    predicates = condition_config.get("all", [])
    if not isinstance(predicates, list):
        raise PolicyInvalidRuleError("condition_config.all must be a list.")
    known = known_predicate_names()
    for entry in predicates:
        if not isinstance(entry, dict) or "predicate" not in entry:
            raise PolicyInvalidRuleError("Each condition entry must include a 'predicate' name.")
        if entry["predicate"] not in known:
            raise PolicyInvalidRuleError(f"Unknown predicate: {entry['predicate']!r}.")


def publish_policy_version(
    *,
    workspace: Workspace,
    policy_version: PolicyVersion,
    actor: User,
    request_id: str | None = None,
) -> PolicyVersion:
    """Freeze this version's rules and make it the workspace's single active
    version for its policy (section 14, 120)."""
    with transaction.atomic():
        locked = PolicyVersion.objects.select_for_update().get(pk=policy_version.pk)
        if locked.status != PolicyVersionStatus.DRAFT:
            raise PolicyVersionNotActivatableError()
        PolicyVersion.objects.filter(
            policy=locked.policy, status=PolicyVersionStatus.ACTIVE
        ).update(status=PolicyVersionStatus.SUPERSEDED)
        locked.status = PolicyVersionStatus.ACTIVE
        locked.published_at = timezone.now()
        locked.save()
        record_event(
            action=AuditAction.POLICY_VERSION_PUBLISHED,
            target_type="policy_version",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"policy_id": str(locked.policy_id), "version": locked.version},
            request_id=request_id,
        )
    return locked


def activate_policy(
    *, workspace: Workspace, policy: Policy, actor: User, request_id: str | None = None
) -> Policy:
    """Make this the workspace's single active policy (section 120)."""
    with transaction.atomic():
        Policy.objects.filter(workspace=workspace, status=PolicyStatus.ACTIVE).exclude(
            pk=policy.pk
        ).update(status=PolicyStatus.INACTIVE)
        locked = Policy.objects.select_for_update().get(pk=policy.pk)
        locked.status = PolicyStatus.ACTIVE
        locked.save()
        record_event(
            action=AuditAction.POLICY_ACTIVATED,
            target_type="policy",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"policy_id": str(locked.id)},
            request_id=request_id,
        )
    return locked


def deactivate_policy(
    *, workspace: Workspace, policy: Policy, actor: User, request_id: str | None = None
) -> Policy:
    with transaction.atomic():
        locked = Policy.objects.select_for_update().get(pk=policy.pk)
        locked.status = PolicyStatus.INACTIVE
        locked.save()
        record_event(
            action=AuditAction.POLICY_DEACTIVATED,
            target_type="policy",
            target_id=locked.id,
            actor=actor,
            workspace=workspace,
            metadata={"policy_id": str(locked.id)},
            request_id=request_id,
        )
    return locked
