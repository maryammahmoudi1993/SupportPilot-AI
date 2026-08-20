"""The deterministic policy evaluator (section 6-9, 16, 25-29 of the Phase 8
brief) — the single function ``evaluate_policy`` that turns a trusted tool
action plus its ``RiskOutcome`` into exactly one normalized decision:
``ALLOW``, ``DENY``, or ``REQUIRE_APPROVAL``.

Never calls an LLM, a provider, or the network (section 147). Given the same
policy version, tool, and canonical arguments, the result is always
identical (section 96) — there is no randomness, no wall-clock-dependent
branching (other than an explicit, documented business-hours predicate this
phase does not implement), and no hidden state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from .defaults import evaluate_system_default, required_role_for_risk
from .errors import PolicyEvaluationFailedError
from .models import POLICY_EFFECT_PRECEDENCE, PolicyEffect, PolicyRule, PolicyVersion
from .predicates import PredicateContext, evaluate_predicate
from .risk import RiskOutcome


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    decision_code: str
    safe_reason: str
    matched_rule_ids: list[str]
    policy_version: PolicyVersion | None
    required_role: str
    approval_ttl_seconds: int


def evaluate_policy(
    *,
    tool_key: str,
    risk: RiskOutcome,
    arguments: dict[str, Any],
    active_version: PolicyVersion | None,
) -> PolicyDecision:
    context = PredicateContext(
        tool_key=tool_key,
        risk_level=risk.effective_risk,
        side_effect_type=risk.side_effect_type,
        arguments=arguments,
    )

    if active_version is None:
        default = evaluate_system_default(
            tool_key=tool_key,
            base_risk=risk.base_risk,
            effective_risk=risk.effective_risk,
            side_effect_type=risk.side_effect_type,
            arguments=arguments,
        )
        return _finalize(
            decision=default.decision,
            decision_code=default.decision_code,
            safe_reason=default.safe_reason,
            matched_rule_ids=[],
            active_version=None,
            matched_rules=[],
            risk=risk,
        )

    rules = list(
        PolicyRule.objects.filter(policy_version=active_version, enabled=True).order_by(
            "priority", "id"
        )
    )
    matched: list[PolicyRule] = []
    for rule in rules:
        if _rule_applies(rule=rule, context=context):
            matched.append(rule)

    if not matched:
        default = evaluate_system_default(
            tool_key=tool_key,
            base_risk=risk.base_risk,
            effective_risk=risk.effective_risk,
            side_effect_type=risk.side_effect_type,
            arguments=arguments,
        )
        return _finalize(
            decision=default.decision,
            decision_code=f"no_matching_rule_fallback:{default.decision_code}",
            safe_reason=default.safe_reason,
            matched_rule_ids=[],
            active_version=active_version,
            matched_rules=[],
            risk=risk,
        )

    effects_present = {rule.effect for rule in matched}
    winning_effect = next(e for e in POLICY_EFFECT_PRECEDENCE if e in effects_present)
    winning_rules = [rule for rule in matched if rule.effect == winning_effect]

    return _finalize(
        decision=winning_effect,
        decision_code=f"rule_matched:{winning_rules[0].name}",
        safe_reason=_safe_reason_for(winning_effect, winning_rules[0]),
        matched_rule_ids=[str(rule.id) for rule in matched],
        active_version=active_version,
        matched_rules=winning_rules,
        risk=risk,
    )


def _rule_applies(*, rule: PolicyRule, context: PredicateContext) -> bool:
    if rule.tool_key and rule.tool_key != context.tool_key:
        return False
    if rule.risk_levels and context.risk_level not in rule.risk_levels:
        return False
    if rule.side_effect_types and context.side_effect_type not in rule.side_effect_types:
        return False
    predicates = (rule.condition_config or {}).get("all", [])
    if not isinstance(predicates, list):
        raise PolicyEvaluationFailedError("Malformed rule condition configuration.")
    for entry in predicates:
        if not isinstance(entry, dict) or "predicate" not in entry:
            raise PolicyEvaluationFailedError("Malformed rule condition configuration.")
        name = entry["predicate"]
        params = {k: v for k, v in entry.items() if k != "predicate"}
        if not evaluate_predicate(name, context, params):
            return False
    return True


def _safe_reason_for(effect: str, rule: PolicyRule) -> str:
    if effect == PolicyEffect.DENY:
        return "Action explicitly denied by workspace policy."
    if effect == PolicyEffect.REQUIRE_APPROVAL:
        return "Action requires approval under workspace policy."
    return "Action explicitly permitted by workspace policy."


def _finalize(
    *,
    decision: str,
    decision_code: str,
    safe_reason: str,
    matched_rule_ids: list[str],
    active_version: PolicyVersion | None,
    matched_rules: list[PolicyRule],
    risk: RiskOutcome,
) -> PolicyDecision:
    required_role = ""
    ttl = settings.POLICIES_DEFAULT_APPROVAL_TTL_SECONDS
    if decision == PolicyEffect.REQUIRE_APPROVAL:
        rule_role = next((r.required_role for r in matched_rules if r.required_role), "")
        required_role = rule_role or required_role_for_risk(risk.effective_risk)
        rule_ttl = next(
            (r.approval_ttl_seconds for r in matched_rules if r.approval_ttl_seconds), None
        )
        ttl = rule_ttl or settings.POLICIES_DEFAULT_APPROVAL_TTL_SECONDS
    return PolicyDecision(
        decision=decision,
        decision_code=decision_code,
        safe_reason=safe_reason,
        matched_rule_ids=matched_rule_ids,
        policy_version=active_version,
        required_role=required_role,
        approval_ttl_seconds=ttl,
    )


def resolve_active_version(*, workspace) -> PolicyVersion | None:
    """The workspace's single active policy's single active version, or
    ``None`` if the workspace has no active custom policy (section 120-121).
    """
    from .models import Policy, PolicyStatus, PolicyVersionStatus

    policy = Policy.objects.filter(workspace=workspace, status=PolicyStatus.ACTIVE).first()
    if policy is None:
        return None
    return PolicyVersion.objects.filter(policy=policy, status=PolicyVersionStatus.ACTIVE).first()
