# ADR 0003: Structured Execution Traces Without Chain-of-Thought

- Status: Accepted
- Date: 2026-08-18

## Context

Operators need to understand what an agent run did — which provider/model it
called, how many tokens it used, whether a budget was hit, whether a
provider call failed and why — without the platform ever storing or exposing
a model's private/internal reasoning ("chain-of-thought"), reasoning tokens,
or scratchpad content. Some vendors return such content; it must never reach
the database or an API response.

## Decision

`AgentStep` is a fixed, enumerated set of *operational* events
(`agents.models.AgentStepType`: `run_started`, `request_normalized`,
`budget_checked`, `provider_call_started/succeeded/failed`,
`response_finalized`, `run_completed/failed/cancelled`). Each row stores only:

- `step_type` / `status` (enumerated, not free text describing reasoning);
- `provider` / `model` (identifiers, not content);
- `input_summary` / `output_summary` (short, length-derived summaries — e.g.
  character counts — never raw private content);
- `safe_metadata` (a small JSON object of operational facts: token counts,
  budget-check outcome, finish reason);
- `latency_ms`, timestamps, and a safe `error_code`.

The provider adapters normalize every vendor response into
`agents.providers.schemas.LLMResponse`, which exposes only `text` (the final
user-visible content), optional `structured_output`, and usage/latency
metadata — there is no field for vendor reasoning content, and adapters do
not read or forward one even when a vendor SDK response object happens to
carry it.

`AgentRun.final_response` stores the single user-visible response text. There
is no field anywhere in the Phase 5 schema sized or named for private
reasoning, a scratchpad, or a "thoughts" transcript.

## Consequences

Benefits:

- an operator, an approval reviewer, or an evaluation harness can reconstruct
  *what happened* without ever seeing *how the model privately reasoned*;
- the enumerated `step_type` keeps trace data queryable and stable, instead
  of accumulating free-form log lines;
- the boundary is structural (the schema has no such field) rather than a
  runtime filter that could be forgotten on a new code path.

Trade-offs:

- a debugging engineer who wants full vendor-side reasoning for troubleshooting
  a hard failure only has the safe trace and the provider's own
  (non-persisted) side channel — this is intentional, not an oversight.
