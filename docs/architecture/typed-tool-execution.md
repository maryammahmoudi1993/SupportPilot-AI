# Typed Tool Registry and Execution Boundary

Phase 6 introduces the controlled boundary between an AI agent and
executable business capability. This document explains the pipeline, the
trust boundary, idempotency/timeout/retry semantics, and how it integrates
with the Phase 5 agent runtime. See also
[ADR 0004](../adr/0004-typed-tool-registry-and-execution-boundary.md) for the
rationale and rejected alternatives.

## The core rule

> The model may propose a tool call. Only server-controlled code decides
> whether, and how, it executes.

Nothing about this is a convention — it is enforced structurally: tools are
Python objects registered by trusted code (`tools.registry`), never
imported from a string a model or a database row supplies; execution
context (workspace, run, deadline) is built from server state and passed
separately from the model's arguments; and exactly one function,
`tools.execution.execute_tool`, is ever allowed to call a handler.

## Pipeline

```text
Agent runtime (graph.py: execute_tool_call node)
        |
        v
tools.execution.execute_tool
        |
        +--> run-state check (AgentRun must be RUNNING)
        +--> registry.get(tool_key)            -> tool_not_registered
        +--> ToolDefinition lookup              -> tool_configuration_error
        +--> ToolBinding resolution              -> tool_not_bound / tool_disabled
        +--> tool-call budget check              -> tool_budget_exceeded
        +--> typed input validation (Pydantic)   -> tool_invalid_input
        +--> effective timeout derivation        -> tool_budget_exceeded (deadline exhausted)
        +--> idempotency resolution + claim       -> tool_idempotency_conflict /
        |                                            tool_execution_in_progress /
        |                                            tool_retry_exhausted / replay
        +--> pending -> running (ToolExecution)
        +--> bounded retry loop
        |        +--> handler invocation (ThreadPoolExecutor + timeout)
        |        +--> typed output validation      -> tool_invalid_output
        +--> redact + persist result/error
        +--> AgentStep safe trace events
        v
ToolExecutionResult (output | reused) or a raised ToolError
```

## Trust boundary: context vs. arguments

| | Source | Trust |
|---|---|---|
| `arguments` | The model's tool-call proposal | Untrusted — validated against a strict (`extra="forbid"`) Pydantic input model before a handler ever sees it |
| `ToolExecutionContext` | Server state: `AgentRun`, `AgentVersion`, workspace, deadline | Trusted — a handler's only source of tenant/run identity |

A model field named `workspace_id` inside `arguments` is inert: the strict
input schema rejects unknown fields outright, and no handler derives
authority from `arguments` even where a field name happens to match.

## Code-owned vs. database-owned

- **Code-owned** (`tools.contracts.ToolSpec`, via `tools.registry`): tool
  identity, the handler itself, input/output schemas, hard-maximum timeout,
  retry policy. This is what actually governs execution.
- **Database-owned** (`tools.models.ToolDefinition`, `ToolBinding`):
  enabled/disabled status, per-binding timeout *tightening*, workspace/
  agent-version authorization. `ToolDefinition.max_retries` and its timeout
  fields are descriptive metadata mirrored from the registry for the API
  catalog — they do not themselves control execution.

`tools.services.sync_tool_definitions` keeps the mirror consistent; the
demo catalog is additionally seeded by a data migration
(`tools/migrations/0002_seed_demo_tool_definitions.py`) so a fresh
deployment has a working catalog without a manual sync step.

## Idempotency

Scope: `(workspace, tool_definition, idempotency_key)`, enforced by a
partial unique database constraint (blank keys are excluded — a request
without a key never deduplicates). This is deliberately broader than
per-`AgentRun`: a business operation like "refund order X" should stay
idempotent across whichever run or agent triggers it, not just within one.

For a repeated key, `execute_tool` resolves one of four outcomes:

1. **Replay** — a prior execution under this key **succeeded**: the stored
   result is returned; the handler is not invoked again.
2. **Conflict** (`tool_idempotency_conflict`) — the same key was used with
   arguments that canonicalize to a different fingerprint (a stable,
   `json.dumps(..., sort_keys=True)`-based SHA-256, never `pickle`/`repr`).
3. **In progress** (`tool_execution_in_progress`) — a prior execution under
   this key is still `pending`/`running`.
4. **Bounded retry** — a prior execution under this key reached a terminal
   *failure* (`failed`/`timed_out`/`cancelled`): the same row is reset to
   `pending` and retried, but only while the row's `attempt_count` is still
   under the tool's total attempt budget (`max_retries + 1`) — a failure
   never resets the counter, so a caller cannot bypass the retry budget by
   simply calling again with the same key.

Concurrency: the create path relies on the database unique constraint, not
an application-level pre-check. A losing concurrent insert is caught as an
`IntegrityError` and re-resolved through the same four-outcome logic against
the row the winner created — so two callers racing the same key can never
both produce a fresh, successful execution.

## Timeouts

Effective timeout = `min(binding-configured timeout, the tool's coded
max_timeout_seconds, the AgentRun's remaining wall time)`. A binding can
only tighten a timeout, never loosen it past the tool's own hard maximum,
and no future step is ever scheduled after the run's deadline has passed.

Enforcement uses a single-worker `ThreadPoolExecutor` with
`future.result(timeout=...)`. Python has no safe way to forcibly kill a
running thread, so a timed-out handler's thread may continue running to
completion in the background after `ToolExecution` is already marked
`timed_out` — this is a documented limitation, not a forced-cancellation
guarantee. The design is deliberately compatible with true process-level
isolation via a dedicated Celery worker in a later phase.

## Retries

Retry eligibility is per-error-code, declared on the tool's `RetryPolicy`
(`retryable_error_codes`); an error code absent from that set never retries,
regardless of remaining budget. Total attempts for one logical execution —
whether accumulated within a single `execute_tool` call or across a
bounded idempotent replay after failure — never exceed
`retry_policy.max_retries + 1`. Exhausting that budget on a retryable error
always surfaces as the stable `tool_retry_exhausted` code (not whichever
underlying error happened to occur last), while a non-retryable error
surfaces as itself on the first attempt.

Timeouts are never auto-retried within a call: the handler thread may still
be running, and blindly retrying a possibly non-idempotent side effect is
unsafe.

## Agent runtime integration

`agents.runtime.graph` gains one node, `execute_tool_call`, between
`generate_response` and `check_budget`:

```text
generate_response --(tool_request)--> execute_tool_call --(continue)--> check_budget --> generate_response
        \--(continue, no tool call)--> validate_provider_result --> finalize_response --> END
        \--(end, error/budget)------------------------------------------------------------> END
```

Two bounds keep this loop finite and prevent the exact
`while model_wants_tool: execute()` shape the platform must avoid:

- **`max_model_calls`** (Phase 5) — every additional turn is another
  `generate_response` call, gated by `check_budget`.
- **`max_tool_calls`** (`AgentVersion.max_tool_calls` /
  `AgentRun.tool_call_count`, Phase 6) — checked by `execute_tool` itself
  before a `ToolExecution` row is even created.

Only the first tool call proposed in a single model turn is honored; extra
calls in the same turn are silently ignored, not queued — a deliberate
simplification that keeps "one round-trip per turn" a structural property
rather than something that needs its own budget. Full multi-call/parallel
tool orchestration is out of scope for this phase.

## Observability boundary

Four places can describe a tool execution; each has a distinct purpose and
none duplicates the others' full payload:

- **Application logs** — structured, correlation-ID-scoped operational
  logging (never secrets).
- **`AgentStep`** — safe, structured trace events
  (`tool_requested`, `tool_execution_started/succeeded/failed/timed_out`,
  `tool_idempotency_reused`, `tool_validation_failed`) scoped to one run.
  No hidden reasoning, ever.
- **`ToolExecution`** — the durable, queryable record of one logical
  invocation: redacted arguments/result, attempt count, timing, safe error.
- **`AuditEvent`** — reserved for security-sensitive *configuration*
  changes (`tool.binding_created/updated/disabled`), not high-volume
  runtime execution events, consistent with the project's existing
  audit-volume philosophy.

## What is explicitly not in this phase

No real business integration (Stripe, Calendar, CRM, email), no generic
HTTP/shell/SQL/code-execution tool, no policy/approval engine gating
execution on risk level, no multi-tool autonomous planning. The registry
holds exactly `demo.echo`, `demo.add`, and `demo.flaky` — deterministic,
offline, side-effect-free tools whose only job is to prove this boundary
end-to-end.
