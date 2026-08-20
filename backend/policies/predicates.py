"""The trusted predicate registry (section 18-20 of the Phase 8 brief).

A ``PolicyRule.condition_config`` is never executable code — it is a small
JSON document of the shape ``{"all": [{"predicate": "<name>", ...params}]}``
naming *server-owned* predicate functions from this module. The database may
configure a predicate's *name and parameters*; the predicate's *behavior* is
always a fixed Python function shipped with the application, exactly mirroring
how ``tools.registry`` keeps tool behavior code-owned while allowing
database-configured bindings.

An unrecognized predicate name is a configuration error, not "false" — the
evaluator (``policies/evaluator.py``) treats it as fail-closed
(``PolicyEvaluationFailedError``), never as a silently-skipped condition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tools.contracts import RiskLevel

from .errors import PolicyEvaluationFailedError

_RISK_ORDER = {level: index for index, level in enumerate(RiskLevel.values)}


@dataclass(frozen=True)
class PredicateContext:
    """Trusted, server-derived facts a predicate may inspect. ``arguments``
    is the tool's own canonical (validated, JSON-mode-dumped) input — never
    raw request bytes, never a mutable object a predicate could accidentally
    write through."""

    tool_key: str
    risk_level: str
    side_effect_type: str
    arguments: dict[str, Any]


Predicate = Callable[[PredicateContext, dict[str, Any]], bool]

_REGISTRY: dict[str, Predicate] = {}


def register(name: str) -> Callable[[Predicate], Predicate]:
    def _wrap(fn: Predicate) -> Predicate:
        _REGISTRY[name] = fn
        return fn

    return _wrap


def evaluate_predicate(name: str, context: PredicateContext, params: dict[str, Any]) -> bool:
    fn = _REGISTRY.get(name)
    if fn is None:
        raise PolicyEvaluationFailedError(f"Unknown predicate: {name!r}.")
    try:
        return bool(fn(context, params))
    except PolicyEvaluationFailedError:
        raise
    except Exception as exc:  # pragma: no cover - defensive, malformed params
        raise PolicyEvaluationFailedError(
            f"Predicate {name!r} received invalid parameters."
        ) from exc


def known_predicate_names() -> frozenset[str]:
    return frozenset(_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Predicate implementations — only what Phase 7's actual tools need
# (section 18: "Only implement predicates required by actual Phase 7 tools").
# ---------------------------------------------------------------------------


@register("tool_is")
def _tool_is(context: PredicateContext, params: dict[str, Any]) -> bool:
    return bool(context.tool_key == params["value"])


@register("risk_level_at_least")
def _risk_level_at_least(context: PredicateContext, params: dict[str, Any]) -> bool:
    threshold = params["value"]
    if threshold not in _RISK_ORDER:
        raise PolicyEvaluationFailedError(f"Unknown risk level in rule config: {threshold!r}.")
    return _RISK_ORDER[context.risk_level] >= _RISK_ORDER[threshold]


@register("side_effect_type_is")
def _side_effect_type_is(context: PredicateContext, params: dict[str, Any]) -> bool:
    return bool(context.side_effect_type == params["value"])


def _numeric_argument(context: PredicateContext, field: str) -> float | None:
    value = context.arguments.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


@register("amount_minor_gt")
def _amount_minor_gt(context: PredicateContext, params: dict[str, Any]) -> bool:
    value = _numeric_argument(context, "amount_minor")
    return value is not None and value > float(params["value"])


@register("amount_minor_gte")
def _amount_minor_gte(context: PredicateContext, params: dict[str, Any]) -> bool:
    value = _numeric_argument(context, "amount_minor")
    return value is not None and value >= float(params["value"])


@register("amount_minor_lt")
def _amount_minor_lt(context: PredicateContext, params: dict[str, Any]) -> bool:
    value = _numeric_argument(context, "amount_minor")
    return value is not None and value < float(params["value"])


@register("amount_minor_lte")
def _amount_minor_lte(context: PredicateContext, params: dict[str, Any]) -> bool:
    value = _numeric_argument(context, "amount_minor")
    return value is not None and value <= float(params["value"])


@register("currency_is")
def _currency_is(context: PredicateContext, params: dict[str, Any]) -> bool:
    currency = context.arguments.get("currency")
    if not isinstance(currency, str):
        return False
    return currency.upper() == str(params["value"]).upper()


@register("argument_equals")
def _argument_equals(context: PredicateContext, params: dict[str, Any]) -> bool:
    return bool(context.arguments.get(params["field"]) == params["value"])


@register("argument_in_allowed_values")
def _argument_in_allowed_values(context: PredicateContext, params: dict[str, Any]) -> bool:
    return context.arguments.get(params["field"]) in params["values"]


@register("booking_duration_minutes_gt")
def _booking_duration_minutes_gt(context: PredicateContext, params: dict[str, Any]) -> bool:
    start_raw = context.arguments.get("start")
    end_raw = context.arguments.get("end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return False
    try:
        start = datetime.fromisoformat(start_raw)
        end = datetime.fromisoformat(end_raw)
    except ValueError:
        return False
    duration_minutes = (end - start).total_seconds() / 60
    return duration_minutes > float(params["value"])
