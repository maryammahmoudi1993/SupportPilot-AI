"""Trusted predicate registry tests (section 18-20, 99)."""

from __future__ import annotations

import pytest

from policies.errors import PolicyEvaluationFailedError
from policies.predicates import PredicateContext, evaluate_predicate, known_predicate_names


def _ctx(**overrides: object) -> PredicateContext:
    defaults: dict[str, object] = dict(
        tool_key="payment.refund",
        risk_level="critical",
        side_effect_type="financial",
        arguments={"amount_minor": 6000, "currency": "usd"},
    )
    defaults.update(overrides)
    return PredicateContext(**defaults)  # type: ignore[arg-type]


class TestPredicates:
    def test_unknown_predicate_fails_closed(self):
        with pytest.raises(PolicyEvaluationFailedError):
            evaluate_predicate("does_not_exist", _ctx(), {})

    def test_tool_is_matches(self):
        assert evaluate_predicate("tool_is", _ctx(), {"value": "payment.refund"}) is True
        assert evaluate_predicate("tool_is", _ctx(), {"value": "other.tool"}) is False

    def test_risk_level_at_least(self):
        assert (
            evaluate_predicate("risk_level_at_least", _ctx(risk_level="high"), {"value": "medium"})
            is True
        )
        assert (
            evaluate_predicate("risk_level_at_least", _ctx(risk_level="low"), {"value": "high"})
            is False
        )

    def test_risk_level_at_least_unknown_level_fails_closed(self):
        with pytest.raises(PolicyEvaluationFailedError):
            evaluate_predicate("risk_level_at_least", _ctx(), {"value": "not_a_real_level"})

    def test_amount_minor_comparisons(self):
        ctx = _ctx(arguments={"amount_minor": 5000})
        assert evaluate_predicate("amount_minor_gt", ctx, {"value": 4999}) is True
        assert evaluate_predicate("amount_minor_gte", ctx, {"value": 5000}) is True
        assert evaluate_predicate("amount_minor_lt", ctx, {"value": 5001}) is True
        assert evaluate_predicate("amount_minor_lte", ctx, {"value": 5000}) is True
        assert evaluate_predicate("amount_minor_gt", ctx, {"value": 5000}) is False

    def test_amount_minor_missing_argument_does_not_match(self):
        ctx = _ctx(arguments={})
        assert evaluate_predicate("amount_minor_gt", ctx, {"value": 0}) is False

    def test_currency_is_case_insensitive(self):
        ctx = _ctx(arguments={"currency": "usd"})
        assert evaluate_predicate("currency_is", ctx, {"value": "USD"}) is True
        assert evaluate_predicate("currency_is", ctx, {"value": "eur"}) is False

    def test_argument_equals_and_in_allowed_values(self):
        ctx = _ctx(arguments={"status": "confirmed"})
        assert (
            evaluate_predicate("argument_equals", ctx, {"field": "status", "value": "confirmed"})
            is True
        )
        assert (
            evaluate_predicate(
                "argument_in_allowed_values",
                ctx,
                {"field": "status", "values": ["confirmed", "pending"]},
            )
            is True
        )
        assert (
            evaluate_predicate(
                "argument_in_allowed_values", ctx, {"field": "status", "values": ["x"]}
            )
            is False
        )

    def test_booking_duration_minutes_gt(self):
        ctx = _ctx(
            arguments={"start": "2030-01-01T10:00:00+00:00", "end": "2030-01-01T11:00:00+00:00"}
        )
        assert evaluate_predicate("booking_duration_minutes_gt", ctx, {"value": 30}) is True
        assert evaluate_predicate("booking_duration_minutes_gt", ctx, {"value": 90}) is False

    def test_booking_duration_malformed_dates_does_not_match(self):
        ctx = _ctx(arguments={"start": "not-a-date", "end": "also-not-a-date"})
        assert evaluate_predicate("booking_duration_minutes_gt", ctx, {"value": 1}) is False

    def test_predicate_with_missing_required_param_fails_closed(self):
        with pytest.raises(PolicyEvaluationFailedError):
            evaluate_predicate("tool_is", _ctx(), {})  # missing "value"

    def test_side_effect_type_is(self):
        ctx = _ctx(side_effect_type="financial")
        assert evaluate_predicate("side_effect_type_is", ctx, {"value": "financial"}) is True
        assert evaluate_predicate("side_effect_type_is", ctx, {"value": "read"}) is False

    def test_currency_is_non_string_argument_does_not_match(self):
        ctx = _ctx(arguments={"currency": 123})
        assert evaluate_predicate("currency_is", ctx, {"value": "USD"}) is False

    def test_known_predicate_names_includes_all_registered(self):
        names = known_predicate_names()
        assert "tool_is" in names
        assert "amount_minor_gt" in names
        assert "booking_duration_minutes_gt" in names
