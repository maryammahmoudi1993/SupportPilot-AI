# ADR 0004: Trusted Typed Tool Registry Instead of Model-Defined Execution

- Status: Accepted
- Date: 2026-08-19

## Context

Phase 5 gave the agent runtime a bounded loop and a normalized provider
boundary, but an agent could not yet *do* anything beyond generating text.
Phase 6 introduces the first path from a model's request to an executable
side effect. The central risk is architectural, not a bug to patch later:
if a model's output can ever choose *what code runs*, every later guarantee
(tenant isolation, RBAC, idempotency, auditability) is undermined at the
root. The design has to make "the model can request an action, but never
choose how it executes" a structural property of the code, not a
convention someone has to remember.

## Decision

1. **Tools are server-owned Python objects, never model- or database-defined
   code.** `tools.contracts.Tool` pairs immutable `ToolSpec` metadata with a
   trusted handler function. Handlers are registered once, in
   `tools.demo_tools`, and looked up by a stable string key
   (`tools.registry.ToolRegistry`). There is no code path that imports a
   string supplied by a model, a database row, or an HTTP request body.
2. **`ToolDefinition` is a queryable mirror of the registry, not a second
   source of truth.** It carries `handler_key` (a registry key, never an
   import path), operational status, and *descriptive* risk/side-effect
   metadata. Retry policy, timeouts, and input/output schemas are read from
   the registry's `ToolSpec` at execution time — a database row can disable
   a tool, but it can never redefine what the tool does.
3. **Context and arguments are structurally separate.** `ToolExecutionContext`
   (workspace, run, deadline, actor) is built entirely from authenticated
   server state and passed to a handler as a distinct keyword from the
   model's `arguments`. A model field named `workspace_id` in its tool call
   is inert — Pydantic's `extra="forbid"` input models reject it outright,
   and even where a field name were accepted, no handler ever reads
   authority from `arguments`.
4. **One controlled execution service.** `tools.execution.execute_tool` is
   the only function that invokes a handler. It performs, in order: run-state
   validation, registry resolution, `ToolBinding` authorization, tool-call
   budget check, typed input validation, effective-timeout derivation,
   idempotency resolution, bounded timeout+retry execution, typed output
   validation, redaction, and persistence. No other module calls a handler
   directly, and no REST endpoint executes a tool outside the agent runtime
   (section 58) — there is deliberately no `POST /execute-tool/`.
5. **Bindings attach to `AgentVersion`, not `AgentDefinition`.** Published
   versions are immutable (reusing the Phase 5 guarantee); a tool can only be
   bound to or unbound from a *draft* version, so a historical run's
   available tool surface never silently changes.
6. **Idempotency is workspace+tool+key scoped, DB-constrained, and replay-
   safe.** A partial unique constraint on `(workspace, tool_definition,
   idempotency_key)` (excluding blank keys) is the actual race-safety
   mechanism — not an application-level pre-check. `execute_tool` resolves
   four outcomes for a repeated key: replay the stored result (success),
   reject as `tool_idempotency_conflict` (different arguments), reject as
   `tool_execution_in_progress` (still running), or allow a bounded retry on
   the same row (prior terminal failure) — capped by the tool's total
   attempt budget so a failure-triggered replay can never reset the retry
   counter. A concurrent duplicate insert is caught as an `IntegrityError`
   on the same constraint and re-resolved as an existing row, so two workers
   racing the same key can never both create a fresh execution.
7. **Timeouts are hard-capped by trusted code, never by the caller.** The
   effective timeout is `min(binding-configured, tool's coded hard maximum,
   remaining AgentRun wall time)`. A binding can only ever *tighten* a
   timeout, never loosen it past the tool's own `max_timeout_seconds`.
   Enforcement uses a single-worker `ThreadPoolExecutor` with
   `future.result(timeout=...)`; Python cannot forcibly kill a running
   thread, so a timed-out handler may continue running in the background —
   this is documented honestly rather than claimed as forced cancellation,
   and the architecture is deliberately compatible with true isolation via a
   Celery worker in a later phase.
8. **The agent graph gets one bounded tool round-trip, not a loop.** The
   LangGraph runtime (`agents.runtime.graph`) adds `execute_tool_call` between
   `generate_response` and `check_budget`. Only the first tool call proposed
   in a single model turn is honored; a successful execution always routes
   back through `check_budget` — never directly back to
   `generate_response` — so the existing `max_model_calls` bound and the new
   `max_tool_calls` bound (`AgentVersion.max_tool_calls` /
   `AgentRun.tool_call_count`) both apply on every iteration. There is no
   `while model_wants_tool: execute()`.
9. **No generic capability exists to misuse.** The registry contains exactly
   `demo.echo`, `demo.add`, and `demo.flaky` — deterministic, offline,
   side-effect-free tools that exercise the platform. There is no
   `http.request`, `shell`, `python_exec`, or SQL-executor tool, and a
   regression test asserts the production registry never gains one.

## Alternatives rejected

- **A generic HTTP/webhook tool** parameterized by a model-supplied URL —
  rejected outright; it collapses the entire boundary into SSRF-by-design.
- **Dynamic import of a handler from a database-stored path/callable name**
  — rejected; it makes the database a code-execution surface and defeats
  static reasoning about what a workspace admin can cause to run.
- **A `while` loop letting the model keep requesting tools until it stops**
  — rejected for this phase; full multi-step orchestration is Phase 9's
  concern, and an unbounded loop is exactly the failure mode Phase 5's
  bounded-runtime rule exists to prevent.
- **Per-request execution endpoint** (`POST .../tools/{key}/execute/`) for
  operator convenience — rejected; every execution must flow through an
  `AgentRun`'s bounded, audited runtime, not an ad hoc authenticated call.

## Consequences

Benefits:

- adding a real integration in Phase 7 (Stripe refund, Calendar event) means
  writing a new `Tool` + typed Pydantic models — the registry, execution
  service, idempotency, timeout, and trace machinery need no changes;
- the "LLM proposes, application decides" boundary is enforced by the type
  system and the database schema, not by hoping every future tool author
  remembers the rule;
- idempotency and concurrency guarantees are real (database-constraint
  backed), not best-effort in-process locking.

Trade-offs:

- retry policy is code-owned rather than operator-configurable per
  workspace; a workspace admin can disable a tool binding or lower its
  effective timeout, but cannot change its retry behavior without a code
  change — an intentional bias toward safety over flexibility in this
  phase;
- the bounded "one tool call per turn" simplification means a model that
  proposes several tool calls in one turn has all but the first silently
  ignored (not queued, not executed later); full parallel/multi-call
  handling is deferred to the later orchestration phase;
- risk level and side-effect classification are descriptive only in Phase 6
  — the policy/approval engine that will actually gate execution on them is
  Phase 8's responsibility.
