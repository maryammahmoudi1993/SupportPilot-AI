"""Deterministic, server-owned classification of a terminal orchestration
error code into a bounded recovery action (Phase 9 Block 5, section 33-40,
73-74).

This is a fixed, reviewable mapping table — never a runtime LLM decision,
and never scattered as ad hoc ``if error_code == ...`` branches through
graph nodes or service functions (section 73). Only ``agents.services``
calls this, at the single point where a claimed run's graph result has
already produced a terminal ``safe_error_code`` that is neither
``approval_required`` nor a budget-exceeded signal (both handled by their
own dedicated, unambiguous branches upstream).

Design (documented, not exhaustive of every conceivable RecoveryAction —
see the module docstring in ``docs/architecture/human-handoff-orchestration.md``
for the full rationale):

* Infrastructure/configuration failures and terminal *tool* failures
  (``tool_configuration_error``, ``policy_evaluation_failed``, an invalid/
  tampered approval action, etc.) always FAIL the run (section 47) — a
  handoff must never masquerade as a fix for a broken system.
* An ordinary, safe *business* tool failure (order not found, calendar
  slot unavailable, ...) never reaches this classifier at all: Block 3's
  ``agents.services._execute_tool_factory`` already routes those into a
  bounded LLM follow-up turn (a ``ToolResultContext`` denial/failure
  message), not a terminal ``safe_error_code`` — the *model itself* may
  then request a handoff on its own next turn if it decides the customer
  still needs a human (section 34-35, 75-76, 82).
* A *provider* failure that Block 3's bounded retry loop already retried
  to exhaustion (rate limit / timeout / temporary outage — never
  authentication or configuration, which fail immediately, non-retryable)
  is not the run's fault and the conversation can still be handed off, so
  it becomes a handoff instead of a bare failure (section 36, 77) —
  provided the run actually has a conversation to hand off to (section
  59-61); otherwise it still fails, since there is nothing to escalate.
* Budget exhaustion is handled entirely separately, before this
  classifier ever runs (``AgentRunStatus.BUDGET_EXCEEDED``, section 39-40)
  — deliberately never reclassified as a handoff, to avoid budget
  exhaustion becoming a way to generate unbounded handoffs.
"""

from __future__ import annotations

import enum


class RecoveryAction(enum.Enum):
    FAIL = "fail"
    HANDOFF = "handoff"


#: Provider failure codes that only ever reach this classifier after Block
#: 3's bounded retry loop (``agents.runtime.graph._route_after_generate``)
#: has already exhausted every retry attempt permitted by
#: ``AgentVersion.max_retry_attempts``/``max_model_calls`` — never on the
#: first attempt. See ``agents.providers.errors`` for the full taxonomy;
#: every code left out here (auth, configuration, invalid request, malformed
#: response, content rejected) is non-retryable and always fails the run.
_RETRYABLE_PROVIDER_HANDOFF_CODES = frozenset(
    {"provider_rate_limited", "provider_timeout", "provider_temporarily_unavailable"}
)


def classify_terminal_failure(*, error_code: str, has_conversation: bool) -> RecoveryAction:
    """Classify one already-terminal ``safe_error_code`` from a graph result.

    Deterministic and total: every input maps to exactly one
    ``RecoveryAction``, and the same input always produces the same output
    (no randomness, no external state, no LLM call).
    """
    if has_conversation and error_code in _RETRYABLE_PROVIDER_HANDOFF_CODES:
        return RecoveryAction.HANDOFF
    return RecoveryAction.FAIL
