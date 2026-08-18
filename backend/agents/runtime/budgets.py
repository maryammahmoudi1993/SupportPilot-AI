"""Deterministic, pre-flight budget checks.

Every budget is checked *before* another expensive action (a provider call)
is scheduled. The runtime never invents cost figures: estimated cost is only
enforced when the agent version has a configured ceiling and the provider
actually reported a cost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Budgets:
    max_model_calls: int
    max_steps: int
    wall_time_limit_seconds: int
    provider_timeout_seconds: int
    max_total_tokens: int | None
    max_estimated_cost_usd: Decimal | None
    max_retry_attempts: int


@dataclass(frozen=True)
class BudgetCheckResult:
    allowed: bool
    reason: str | None = None


def check_budget(
    *,
    budgets: Budgets,
    model_call_count: int,
    step_count: int,
    total_tokens: int,
    estimated_cost_usd: Decimal | None,
    started_monotonic: float,
) -> BudgetCheckResult:
    """Return whether another model call may be scheduled right now."""
    if model_call_count >= budgets.max_model_calls:
        return BudgetCheckResult(False, "max_model_calls_reached")
    if step_count >= budgets.max_steps:
        return BudgetCheckResult(False, "max_steps_reached")
    elapsed = time.monotonic() - started_monotonic
    if elapsed >= budgets.wall_time_limit_seconds:
        return BudgetCheckResult(False, "wall_time_limit_reached")
    if budgets.max_total_tokens is not None and total_tokens >= budgets.max_total_tokens:
        return BudgetCheckResult(False, "max_total_tokens_reached")
    if (
        budgets.max_estimated_cost_usd is not None
        and estimated_cost_usd is not None
        and estimated_cost_usd >= budgets.max_estimated_cost_usd
    ):
        return BudgetCheckResult(False, "max_estimated_cost_reached")
    return BudgetCheckResult(True)
