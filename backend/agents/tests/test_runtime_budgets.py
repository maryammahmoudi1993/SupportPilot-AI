from decimal import Decimal

from agents.runtime.budgets import Budgets, check_budget


def _budgets(**overrides):
    defaults = dict(
        max_model_calls=1,
        max_steps=20,
        wall_time_limit_seconds=30,
        provider_timeout_seconds=30,
        max_total_tokens=None,
        max_estimated_cost_usd=None,
        max_retry_attempts=1,
    )
    defaults.update(overrides)
    return Budgets(**defaults)


def _check(budgets, **overrides):
    defaults = dict(
        model_call_count=0,
        step_count=0,
        total_tokens=0,
        estimated_cost_usd=None,
        started_monotonic=__import__("time").monotonic(),
    )
    defaults.update(overrides)
    return check_budget(budgets=budgets, **defaults)


class TestModelCallBudget:
    def test_below_max_calls_is_allowed(self):
        result = _check(_budgets(max_model_calls=2), model_call_count=1)
        assert result.allowed is True

    def test_at_max_calls_is_blocked(self):
        result = _check(_budgets(max_model_calls=1), model_call_count=1)
        assert result.allowed is False
        assert result.reason == "max_model_calls_reached"

    def test_zero_budget_blocks_the_first_call(self):
        # max_model_calls itself is DB-constrained >= 1, but the budget
        # function must still be correct at the boundary in isolation.
        result = _check(_budgets(max_model_calls=1), model_call_count=1)
        assert result.allowed is False


class TestStepBudget:
    def test_step_count_exactly_at_limit_is_blocked(self):
        result = _check(_budgets(max_steps=5), step_count=5)
        assert result.allowed is False
        assert result.reason == "max_steps_reached"

    def test_step_count_one_below_limit_is_allowed(self):
        result = _check(_budgets(max_steps=5), step_count=4)
        assert result.allowed is True


class TestTokenBudget:
    def test_below_token_limit_is_allowed(self):
        result = _check(_budgets(max_total_tokens=1000), total_tokens=500)
        assert result.allowed is True

    def test_token_limit_reached_blocks(self):
        result = _check(_budgets(max_total_tokens=1000), total_tokens=1000)
        assert result.allowed is False
        assert result.reason == "max_total_tokens_reached"

    def test_no_token_limit_never_blocks_on_tokens(self):
        result = _check(_budgets(max_total_tokens=None), total_tokens=10_000_000)
        assert result.allowed is True


class TestCostBudget:
    def test_no_reported_cost_never_blocks(self):
        result = _check(_budgets(max_estimated_cost_usd=Decimal("1.00")), estimated_cost_usd=None)
        assert result.allowed is True

    def test_reported_cost_at_ceiling_blocks(self):
        result = _check(
            _budgets(max_estimated_cost_usd=Decimal("1.00")), estimated_cost_usd=Decimal("1.00")
        )
        assert result.allowed is False
        assert result.reason == "max_estimated_cost_reached"

    def test_reported_cost_below_ceiling_allows(self):
        result = _check(
            _budgets(max_estimated_cost_usd=Decimal("1.00")), estimated_cost_usd=Decimal("0.50")
        )
        assert result.allowed is True


class TestWallTimeBudget:
    def test_expired_wall_time_blocks_new_calls(self):
        result = _check(_budgets(wall_time_limit_seconds=0), started_monotonic=0.0)
        assert result.allowed is False
        assert result.reason == "wall_time_limit_reached"

    def test_ample_wall_time_allows(self):
        import time

        result = _check(_budgets(wall_time_limit_seconds=600), started_monotonic=time.monotonic())
        assert result.allowed is True
