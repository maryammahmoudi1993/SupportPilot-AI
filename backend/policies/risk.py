"""Deterministic risk assessment (section 21-24 of the Phase 8 brief).

``assess_risk`` never asks the LLM anything and never depends on network or
provider calls — it is a pure function of trusted, already-validated inputs:
the tool's code-owned ``ToolSpec``/``ToolDefinition`` risk metadata plus the
tool's own canonical (schema-validated) arguments. Same inputs always
produce the same output (section 96).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from tools.contracts import RiskLevel, SideEffectType

_RISK_ORDER = {level: index for index, level in enumerate(RiskLevel.values)}


@dataclass(frozen=True)
class RiskOutcome:
    base_risk: str
    effective_risk: str
    side_effect_type: str
    factors: dict[str, Any]


def _bump(level: str) -> str:
    order = _RISK_ORDER[level]
    if order + 1 >= len(RiskLevel.values):
        return level
    return RiskLevel.values[order + 1]


def assess_risk(
    *, tool_key: str, base_risk: str, side_effect_type: str, arguments: dict[str, Any]
) -> RiskOutcome:
    """Compute the effective risk of one already-validated tool action.

    Dynamic adjustment (section 22) is intentionally narrow and explicit: a
    financial action whose ``amount_minor`` meets or exceeds the configured
    bump threshold is escalated by exactly one risk tier. Every other tool
    keeps its code-owned base risk unchanged — there is no generic
    "argument size implies danger" heuristic, only this one documented rule.
    """
    factors: dict[str, Any] = {
        "base_risk": base_risk,
        "side_effect_type": side_effect_type,
        "financial": side_effect_type == SideEffectType.FINANCIAL,
        "external_write": side_effect_type
        in (SideEffectType.EXTERNAL_WRITE, SideEffectType.FINANCIAL),
    }

    amount_minor = arguments.get("amount_minor")
    if isinstance(amount_minor, int | float) and not isinstance(amount_minor, bool):
        factors["amount_minor"] = amount_minor
    currency = arguments.get("currency")
    if isinstance(currency, str):
        factors["currency"] = currency.upper()

    effective_risk = base_risk
    if (
        side_effect_type == SideEffectType.FINANCIAL
        and isinstance(amount_minor, int | float)
        and not isinstance(amount_minor, bool)
        and amount_minor >= settings.POLICIES_RISK_BUMP_FINANCIAL_AMOUNT_MINOR
    ):
        effective_risk = _bump(base_risk)
        factors["risk_bumped"] = True

    return RiskOutcome(
        base_risk=base_risk,
        effective_risk=effective_risk,
        side_effect_type=side_effect_type,
        factors=factors,
    )
