# Human Handoff Orchestration and Failure/Recovery Semantics

Phase 9 Block 5 turns Block 1's `HumanHandoff` foundation into a third orchestration outcome
alongside autonomous completion and authorized (approval-gated) completion:

```text
Can safely complete            -> final response
Needs authorized business action -> tool -> policy -> approval -> resume -> final response
Cannot/should not safely complete -> HumanHandoff -> deterministic acknowledgement -> HANDED_OFF
```

## Handoff is not a tool

A handoff request is a distinct, typed field on the normalized LLM response
(`NormalizedHandoffRequest`/`LLMResponse.handoff_request`), never a registered `Tool`. It never
creates a `ToolExecution` row, never enters the deterministic risk/policy gate, and never consumes
the `max_tool_calls` budget — a human escalation is a control-flow decision, not a business action
with a side effect requiring authorization. The model's only inputs are `reason_code` and
`summary`; `NormalizedHandoffRequest` has no `workspace_id`, `assigned_to`, `staff_role`,
`ticket_id`, or priority field at all, so the model has no *shape* through which to propose one —
those facts are always read from the triggering `AgentRun`'s own trusted fields.

## Routing precedence

`agents.runtime.graph._generate_response` checks `response.handoff_request` before
`response.tool_calls`: if the model proposes a handoff, no tool call is honored that turn, even if
the provider also returned one — this is the deterministic "handoff > tool" precedence. The bounded
"one action per model turn" invariant Block 3 established is preserved without introducing a
three-way `route_model_result` abstraction: handoff is simply a second, mutually-exclusive pending
action alongside `pending_tool_call`, checked first.

## Two-phase creation closes the cancel race

The `execute_handoff_request` graph node only *validates* the request (reason code against the
server-owned `HumanHandoffReason` enum, non-empty summary) and returns a `handoff_request` fact in
state — it never writes a `HumanHandoff` row. `agents.services._complete_run_as_handoff` performs
the actual `tickets.services.create_or_reuse_handoff` call *inside* the same
`select_for_update`-guarded transaction that checks `AgentRun.status == RUNNING` and transitions it
to `HANDED_OFF`. A concurrent `cancel_agent_run` that wins the row lock first leaves
`_complete_run_as_handoff` returning early — no `HumanHandoff` row is ever created for a run that a
race has already cancelled. This mirrors how Block 4's approval creation is nested inside the same
atomic block as its `ToolExecution` status transition.

## Terminal state

`AgentRunStatus.HANDED_OFF` joins `AGENT_RUN_TERMINAL_STATUSES` — no further LLM call, tool call,
or provider side effect may occur for that run, and `cancel_agent_run` correctly refuses to cancel
an already-handed-off run. The graph routes `execute_handoff_request` straight to `END`
unconditionally (success or validation failure): a handoff never spends an extra model call to
formulate its own acknowledgement, which is always the deterministic, server-owned
`agents.services.HANDOFF_ACKNOWLEDGEMENT_TEXT` — never a promise of a specific response time or
staff member. The acknowledgement is persisted through the same `AgentRun.output_message`
OneToOneField invariant Block 1 established, so a duplicate/redelivered completion never creates a
second message.

## Active-handoff start guard

`agents.orchestration.execute_support_agent_run` checks
`tickets.selectors.active_handoff_for_conversation` before spending any RAG/LLM cost: a
conversation already awaiting a human never gets a second autonomous run for a new inbound
message. `agents.services.complete_run_via_existing_active_handoff` completes the new run
immediately by calling the same `_complete_run_as_handoff` path with a synthetic
`handoff_request`, which `create_or_reuse_handoff` correctly resolves to the conversation's
existing active handoff (`created=False`) rather than creating a second one — no new selector or
duplicate-detection logic was needed beyond Block 1's own partial unique constraint. A resolved (or
cancelled) handoff never blocks a later escalation: the guard only matches PENDING/ASSIGNED
statuses.

## Failure classification

`agents.failure_classification.classify_terminal_failure` is the single, reviewable table mapping
an already-terminal `safe_error_code` to `RESPOND`/`HANDOFF`/`FAIL` — no `if error_code == ...`
scattered through graph nodes. Most failure handling needs no new classification at all:

* An ordinary safe *business* tool failure (order not found, calendar slot unavailable, ...) never
  reaches this classifier — Block 3's `_execute_tool_factory` already routes it into a bounded LLM
  follow-up turn as a `ToolResultContext` denial, and the model may then request a handoff on its
  own next turn if it decides the customer still needs a human. No server-side escalation policy is
  needed for this path; it is entirely emergent from combining Block 3's tool-result trust boundary
  with the new handoff channel.
* Infrastructure/configuration failures and terminal tool failures (`tool_configuration_error`,
  `policy_evaluation_failed`, a tampered approved action, provider authentication/configuration
  errors) always `FAIL` the run — a handoff must never masquerade as a fix for a broken system.
* A provider failure that Block 3's bounded retry loop already retried to exhaustion
  (`provider_rate_limited`, `provider_timeout`, `provider_temporarily_unavailable` — never
  authentication/configuration, which are non-retryable and fail immediately) becomes a
  deterministic, server-owned `HANDOFF` (reason `runtime_failure`) instead of a bare failure,
  provided the run actually has a conversation to hand off to; otherwise it still fails, since there
  is nothing to escalate.
* Budget exhaustion (`AgentRunStatus.BUDGET_EXCEEDED`) is handled entirely separately and never
  reclassified as a handoff, so budget exhaustion can never become a way to generate unbounded
  handoffs.

## Reason codes

Block 5 reuses Block 1's existing `tickets.models.HumanHandoffReason` taxonomy rather than
introducing a second, competing enum:

| Value                 | Used for                                                          |
| ---------------------- | ------------------------------------------------------------------ |
| `customer_requested`   | The customer explicitly asked for a human, or a new message arrived on an already-actively-escalated conversation. |
| `unsupported_action`   | The model determines the request is outside what it can safely do. |
| `runtime_failure`      | Automated recovery after a bounded-retry-exhausted provider failure. |
| `low_confidence`       | Available to the model; not triggered by any server-owned path in Block 5. |
| `policy_escalation`    | Available to the model for "this needs an operator" business-workflow cases. |

A reason code outside this enum fails closed (`invalid_handoff_reason`) — never silently remapped
to a guessed value.

## Ticket linkage

`_request_handoff_factory`/`_complete_run_as_handoff` pass `ticket=run.ticket` — server-derived,
never model input. Block 5 does not auto-create a ticket for a handoff; if `AgentRun.ticket` is
`None`, `HumanHandoff.ticket` stays `None`, consistent with Block 1's design. No new ticket-creation
logic was added.

## No chain-of-thought

`safe_summary` is the model's plain-text proposal, clamped to 2000 characters at the provider
normalization boundary and again to 500 characters by `HumanHandoff.save()`. It is stored and
retrieved as an inert string — never executed, never templated, and the approver-facing
`ApprovalDecision.safe_comment` equivalent for handoffs (there is none — handoffs have no private
staff comment field) never reaches this path.
