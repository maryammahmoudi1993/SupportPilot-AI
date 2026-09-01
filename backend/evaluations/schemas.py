"""Typed, schema-validated JSON structures for evaluation cases.

Nothing here deserializes executable code. Every flexible JSON structure a
case may carry — seeded business context, tool/approval/outcome expectations
— is a bounded Pydantic model with a fixed, code-owned vocabulary (section
17-18 of the Phase 12 brief). ``extra="forbid"`` everywhere so an unexpected
key fails validation loudly instead of being silently ignored or later
interpreted as something dynamic.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Seeded business context (section 19)
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeededCustomer(_StrictModel):
    external_id: str = ""
    name: str = ""
    email: str = ""
    metadata: dict = Field(default_factory=dict)


class SeededOrder(_StrictModel):
    external_id: str
    status: str = "completed"
    total_amount: str = "0.00"
    currency: str = "USD"
    metadata: dict = Field(default_factory=dict)


class SeededPayment(_StrictModel):
    external_id: str
    order_external_id: str = ""
    amount: str = "0.00"
    currency: str = "USD"
    status: str = "captured"
    metadata: dict = Field(default_factory=dict)


class SeededShipment(_StrictModel):
    external_id: str
    order_external_id: str = ""
    status: str = "in_transit"
    metadata: dict = Field(default_factory=dict)


class SeededCalendarSlot(_StrictModel):
    external_id: str
    starts_at: str
    ends_at: str
    available: bool = True


class SeededKnowledgeDocument(_StrictModel):
    title: str
    content: str
    citation_id: str = ""


class EvaluationSeededContext(_StrictModel):
    """Deterministic synthetic business context for one case.

    Never resolves objects in another workspace (section 19) — this is a
    plain data bag consumed by fake providers seeded per-case, not a set of
    live foreign keys into any workspace's real data.
    """

    customer: SeededCustomer | None = None
    orders: list[SeededOrder] = Field(default_factory=list)
    payments: list[SeededPayment] = Field(default_factory=list)
    shipments: list[SeededShipment] = Field(default_factory=list)
    calendar_slots: list[SeededCalendarSlot] = Field(default_factory=list)
    knowledge_documents: list[SeededKnowledgeDocument] = Field(default_factory=list)
    # Deterministic LLM behavior for this case, consumed directly by
    # ``DeterministicFakeLLMProvider`` (one scenario per expected model call).
    llm_scenarios: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Case expectations (section 17-18)
# ---------------------------------------------------------------------------

ApprovalBehavior = Literal[
    "not_required",
    "required",
    "approved_path",
    "rejected_path",
    "handoff_expected",
]

#: Bounded, code-owned predicate vocabulary. Deliberately not an arbitrary
#: expression language (section 18, 67) — each type names one safe,
#: structurally-checkable fact about the run.
OutcomeAssertionType = Literal[
    "run_terminal_state_equals",
    "handoff_created",
    "approval_created",
    "tool_succeeded",
    "tool_not_executed",
    "response_contains_citation",
]


class OutcomeAssertion(_StrictModel):
    type: OutcomeAssertionType
    value: str | None = None
    tool: str | None = None


class EvaluationCaseExpectations(_StrictModel):
    expected_intent: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    required_tool_sequence: list[str] | None = None
    acceptable_tool_sequences: list[list[str]] | None = None
    approval_behavior: ApprovalBehavior | None = None
    outcome_assertions: list[OutcomeAssertion] = Field(default_factory=list)
    reference_answer: str | None = None
    risk_constraints: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scorer output (section 25-27) — raw metric values only, never a decision
# baked in silently. Kept separate from pass/fail (EvaluationResult.passed)
# and from run/dataset aggregates (section 26).
# ---------------------------------------------------------------------------


class EvaluationScorerOutput(_StrictModel):
    intent_evaluated: bool = False
    intent_correct: bool | None = None
    tool_selection_correct: bool | None = None
    forbidden_tool_violation: bool = False
    forbidden_tools_attempted: list[str] = Field(default_factory=list)
    required_sequence_compliant: bool | None = None
    approval_compliant: bool | None = None
    approval_violation: bool = False
    handoff_occurred: bool = False
    outcome_assertions_passed: int = 0
    outcome_assertions_failed: int = 0
    outcome_assertion_failures: list[str] = Field(default_factory=list)
    citation_present: bool | None = None
    latency_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: str | None = None


def validate_seeded_context(data: dict) -> dict:
    """Validate ``data`` as :class:`EvaluationSeededContext`, returning a
    plain JSON-safe dict. Raises ``pydantic.ValidationError`` on any
    unexpected shape."""

    return EvaluationSeededContext.model_validate(data).model_dump(mode="json")


def validate_case_expectations(data: dict) -> dict:
    """Validate ``data`` as :class:`EvaluationCaseExpectations`, returning a
    plain JSON-safe dict. Raises ``pydantic.ValidationError`` on any
    unexpected shape."""

    return EvaluationCaseExpectations.model_validate(data).model_dump(mode="json")
