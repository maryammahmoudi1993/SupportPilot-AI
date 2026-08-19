"""Code-owned system default policy (section 31, 122-123 of the Phase 8
brief).

Applied only when a workspace has not activated a custom ``Policy`` — a
workspace never has to configure anything before read-only tools work, but a
side-effecting tool is never silently unrestricted either. These defaults
are a system safety floor: nothing in the workspace-configurable
``PolicyRule`` model can weaken them for a workspace that simply never
created a policy, and no workspace-owned ``PolicyRule`` can be used to make
this module's decisions less safe than what it already returns — a custom
active policy fully replaces (not merges with) these defaults, by design
(section 121: "a workspace policy set plus explicit rule matching is
sufficient").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from tools.contracts import RiskLevel, SideEffectType
from workspaces.models import WorkspaceRole

from .models import PolicyEffect


@dataclass(frozen=True)
class DefaultDecision:
    decision: str
    decision_code: str
    safe_reason: str


# Server-owned mapping from effective risk to the minimum workspace role
# able to decide a REQUIRE_APPROVAL action for it (section 48). Read-only/low
# risk never reaches an approval gate under the default policy, so they are
# intentionally absent here.
DEFAULT_REQUIRED_ROLE_BY_RISK: dict[str, str] = {
    RiskLevel.MEDIUM: WorkspaceRole.SUPPORT_MANAGER,
    RiskLevel.HIGH: WorkspaceRole.ADMIN,
    RiskLevel.CRITICAL: WorkspaceRole.OWNER,
}


def required_role_for_risk(effective_risk: str) -> str:
    return DEFAULT_REQUIRED_ROLE_BY_RISK.get(effective_risk, WorkspaceRole.OWNER)


def evaluate_system_default(
    *,
    tool_key: str,
    base_risk: str,
    effective_risk: str,
    side_effect_type: str,
    arguments: dict[str, Any],
) -> DefaultDecision:
    """The deterministic fallback used whenever no active workspace
    ``PolicyVersion`` governs this action (section 28, 98, 122)."""

    if side_effect_type == SideEffectType.READ or base_risk == RiskLevel.READ_ONLY:
        return DefaultDecision(
            decision=PolicyEffect.ALLOW,
            decision_code="system_default_read_only_allow",
            safe_reason="Read-only lookup permitted by default workspace policy.",
        )

    if tool_key == "payment.refund":
        return _refund_default(arguments)

    if side_effect_type == SideEffectType.FINANCIAL:
        return DefaultDecision(
            decision=PolicyEffect.REQUIRE_APPROVAL,
            decision_code="system_default_financial_requires_approval",
            safe_reason="Financial action requires manager approval by default workspace policy.",
        )

    if side_effect_type == SideEffectType.EXTERNAL_WRITE:
        return DefaultDecision(
            decision=PolicyEffect.REQUIRE_APPROVAL,
            decision_code="system_default_external_write_requires_approval",
            safe_reason="This action affects an external system and requires approval by default.",
        )

    if side_effect_type == SideEffectType.DESTRUCTIVE:
        return DefaultDecision(
            decision=PolicyEffect.REQUIRE_APPROVAL,
            decision_code="system_default_destructive_requires_approval",
            safe_reason="Destructive actions require approval by default workspace policy.",
        )

    if side_effect_type == SideEffectType.INTERNAL_WRITE:
        return DefaultDecision(
            decision=PolicyEffect.ALLOW,
            decision_code="system_default_internal_write_allow",
            safe_reason="Internal-only write permitted by default workspace policy.",
        )

    if effective_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        return DefaultDecision(
            decision=PolicyEffect.REQUIRE_APPROVAL,
            decision_code="system_default_high_risk_requires_approval",
            safe_reason="High-risk action requires approval by default workspace policy.",
        )

    return DefaultDecision(
        decision=PolicyEffect.ALLOW,
        decision_code="system_default_low_risk_allow",
        safe_reason="Low-risk action permitted by default workspace policy.",
    )


def _refund_default(arguments: dict[str, Any]) -> DefaultDecision:
    """The at-least-one meaningful deterministic refund policy required by
    section 32-34. A threshold configured for USD never silently applies to
    another currency — an unconfigured currency always requires approval."""

    amount_minor = arguments.get("amount_minor")
    currency = arguments.get("currency")
    if (
        not isinstance(amount_minor, int | float)
        or isinstance(amount_minor, bool)
        or not isinstance(currency, str)
        or currency.upper() != "USD"
    ):
        return DefaultDecision(
            decision=PolicyEffect.REQUIRE_APPROVAL,
            decision_code="system_default_refund_unconfigured_currency",
            safe_reason="Refund currency has no configured automatic threshold; approval required.",
        )

    auto_allow_max = settings.POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR
    approval_max = settings.POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR

    if amount_minor <= auto_allow_max:
        return DefaultDecision(
            decision=PolicyEffect.ALLOW,
            decision_code="system_default_refund_below_auto_threshold",
            safe_reason="Refund is within the automatic refund threshold.",
        )
    if amount_minor <= approval_max:
        return DefaultDecision(
            decision=PolicyEffect.REQUIRE_APPROVAL,
            decision_code="system_default_refund_requires_approval",
            safe_reason="Refund exceeds the automatic refund threshold and requires approval.",
        )
    return DefaultDecision(
        decision=PolicyEffect.DENY,
        decision_code="system_default_refund_exceeds_maximum",
        safe_reason="Refund exceeds the maximum amount workspace policy allows.",
    )
