"""System default policy branch coverage (section 31, 122-123) beyond what
test_evaluator.py already exercises via evaluate_policy()."""

from __future__ import annotations

from policies.defaults import evaluate_system_default
from policies.models import PolicyEffect
from tools.contracts import RiskLevel, SideEffectType


class TestSystemDefaultBranches:
    def test_generic_financial_tool_other_than_refund_requires_approval(self):
        result = evaluate_system_default(
            tool_key="payment.charge",
            base_risk=RiskLevel.HIGH,
            effective_risk=RiskLevel.HIGH,
            side_effect_type=SideEffectType.FINANCIAL,
            arguments={},
        )
        assert result.decision == PolicyEffect.REQUIRE_APPROVAL
        assert result.decision_code == "system_default_financial_requires_approval"

    def test_destructive_requires_approval(self):
        result = evaluate_system_default(
            tool_key="records.purge",
            base_risk=RiskLevel.HIGH,
            effective_risk=RiskLevel.HIGH,
            side_effect_type=SideEffectType.DESTRUCTIVE,
            arguments={},
        )
        assert result.decision == PolicyEffect.REQUIRE_APPROVAL
        assert result.decision_code == "system_default_destructive_requires_approval"

    def test_high_risk_with_no_side_effect_match_requires_approval(self):
        result = evaluate_system_default(
            tool_key="some.tool",
            base_risk=RiskLevel.HIGH,
            effective_risk=RiskLevel.HIGH,
            side_effect_type=SideEffectType.NONE,
            arguments={},
        )
        assert result.decision == PolicyEffect.REQUIRE_APPROVAL
        assert result.decision_code == "system_default_high_risk_requires_approval"

    def test_low_risk_with_no_side_effect_match_allows(self):
        result = evaluate_system_default(
            tool_key="some.tool",
            base_risk=RiskLevel.LOW,
            effective_risk=RiskLevel.LOW,
            side_effect_type=SideEffectType.NONE,
            arguments={},
        )
        assert result.decision == PolicyEffect.ALLOW
        assert result.decision_code == "system_default_low_risk_allow"
