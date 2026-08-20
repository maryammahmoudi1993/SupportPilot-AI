"""Deterministic risk assessment tests (section 21-24, 96)."""

from __future__ import annotations

from policies.risk import assess_risk
from tools.contracts import RiskLevel, SideEffectType


class TestAssessRisk:
    def test_base_risk_carried_through_unchanged_for_non_financial(self):
        outcome = assess_risk(
            tool_key="ticket.create",
            base_risk=RiskLevel.MEDIUM,
            side_effect_type=SideEffectType.INTERNAL_WRITE,
            arguments={},
        )
        assert outcome.base_risk == RiskLevel.MEDIUM
        assert outcome.effective_risk == RiskLevel.MEDIUM
        assert outcome.factors["financial"] is False

    def test_financial_amount_below_bump_threshold_is_unchanged(self, settings):
        settings.POLICIES_RISK_BUMP_FINANCIAL_AMOUNT_MINOR = 100_000
        outcome = assess_risk(
            tool_key="payment.refund",
            base_risk=RiskLevel.HIGH,
            side_effect_type=SideEffectType.FINANCIAL,
            arguments={"amount_minor": 1000, "currency": "usd"},
        )
        assert outcome.effective_risk == RiskLevel.HIGH
        assert "risk_bumped" not in outcome.factors

    def test_financial_amount_at_or_above_bump_threshold_escalates_one_tier(self, settings):
        settings.POLICIES_RISK_BUMP_FINANCIAL_AMOUNT_MINOR = 100_000
        outcome = assess_risk(
            tool_key="payment.refund",
            base_risk=RiskLevel.HIGH,
            side_effect_type=SideEffectType.FINANCIAL,
            arguments={"amount_minor": 100_000, "currency": "usd"},
        )
        assert outcome.effective_risk == RiskLevel.CRITICAL
        assert outcome.factors["risk_bumped"] is True

    def test_bump_never_escalates_past_critical(self, settings):
        settings.POLICIES_RISK_BUMP_FINANCIAL_AMOUNT_MINOR = 100
        outcome = assess_risk(
            tool_key="payment.refund",
            base_risk=RiskLevel.CRITICAL,
            side_effect_type=SideEffectType.FINANCIAL,
            arguments={"amount_minor": 1_000_000, "currency": "usd"},
        )
        assert outcome.effective_risk == RiskLevel.CRITICAL

    def test_currency_normalized_to_uppercase_in_factors(self):
        outcome = assess_risk(
            tool_key="payment.refund",
            base_risk=RiskLevel.CRITICAL,
            side_effect_type=SideEffectType.FINANCIAL,
            arguments={"amount_minor": 500, "currency": "usd"},
        )
        assert outcome.factors["currency"] == "USD"

    def test_non_numeric_amount_minor_is_ignored_not_crashed(self):
        outcome = assess_risk(
            tool_key="payment.refund",
            base_risk=RiskLevel.CRITICAL,
            side_effect_type=SideEffectType.FINANCIAL,
            arguments={"amount_minor": "not-a-number"},
        )
        assert "amount_minor" not in outcome.factors
        assert outcome.effective_risk == RiskLevel.CRITICAL

    def test_determinism_same_inputs_same_output(self):
        kwargs = dict(
            tool_key="payment.refund",
            base_risk=RiskLevel.HIGH,
            side_effect_type=SideEffectType.FINANCIAL,
            arguments={"amount_minor": 100_000, "currency": "usd"},
        )
        first = assess_risk(**kwargs)
        second = assess_risk(**kwargs)
        assert first == second
