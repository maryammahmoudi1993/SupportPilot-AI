# ADR 0007: Bounded Persistent Agent Orchestration with Database-Authoritative Approval and Handoff State

- Status: Accepted
- Date: 2026-08-24

## Context

Phases 5-8 built a bounded execution runtime, a typed tool boundary,
business integrations, and a policy/approval engine — but each was proven
in isolation, driving a single tool round-trip from a synthetic
`AgentRun`, not a real customer conversation. Phase 9 has to combine RAG,
the LLM, the tool boundary, policy, approval, and a third outcome —
handing off to a human — into one orchestration service, without letting
the combination itself become a new authority the model can talk its way
into. A model that can chain "answer, then look something up, then ask for
approval, then escalate" across several turns has correspondingly more
surface to attempt a workspace spoof, a fabricated approval, or a
disguised infinite loop than any single-tool-round-trip test could expose.

## Decisions

1. **LangGraph remains the orchestration engine** — Phase 9 adds a
   `HANDOFF_REQUESTED`/`execute_handoff_request` route and RAG/context
   preparation nodes to the existing graph rather than introducing a
   second execution engine for the "bigger" flow. The bounded-loop
   guarantees Phase 5/6 already proved (budget checks before every call,
   `check_budget` as the resume entry point) extend to the fuller flow for
   free.
2. **Database domain state remains the source of truth**, never the
   model's own claims. `AgentRun.status`, `ApprovalRequest.status`,
   `HumanHandoff.status` are the only record of where a conversation
   actually is; the model never receives or is asked to preserve any of
   this as its own state.
3. **One executed tool per model turn.** A response proposing several tool
   calls has its first eligible one executed and the rest recorded as
   ignored — never queued, never executed in parallel.
4. **Sequential tools only.** No fan-out; a multi-tool flow is several
   single-tool turns, each independently policy-gated.
5. **LLM output is a proposal, never authoritative data.** A tool name, a
   handoff `reason_code`, or a "final" answer are all inputs the server
   validates before acting — never facts the server records because the
   model said so.
6. **RAG and tool output are always untrusted.** Delimited, clearly-marked
   ("TOOL RESULT — UNTRUSTED EXTERNAL DATA") text fed back to the model —
   never elevated to instructions, never trusted as a citation unless the
   server itself retrieved that exact chunk.
7. **An approval binds one frozen action.** `ApprovalRequest` references
   one `ToolExecution`'s already-validated, already-fingerprinted argument
   snapshot; approving it can never be reinterpreted as authorizing a
   different amount, a different tool, or "the agent in general."
8. **Approval releases the worker while waiting.** `WAITING_FOR_APPROVAL`
   holds no thread, Celery task, or DB transaction open — a human can take
   an arbitrary amount of time to decide.
9. **The same `AgentRun` resumes** — not a new run, not a replayed graph
   from `START`. Resume enters the existing graph at `check_budget` with
   the run's own persisted counters (ADR 0006, decision 9), so the
   approval/handoff continuation inherits the exact same budget and
   termination guarantees as the original turn.
10. **`HumanHandoff` is a distinct terminal outcome**, not a tool and not a
    generic exception catch-all. It is reachable only through an explicit
    model request or a specific, code-owned failure classification
    (`agents/failure_classification.py`) — never as the default behavior
    for "something went wrong."
11. **Budgets never reset.** Not on approval resume, not on a handoff
    completion, not on a redelivered task. A counter only ever increases
    until the run reaches a terminal state.
12. **The final response always persists as a `Conversation` `Message`**,
    through the same `output_message` `OneToOneField` invariant, whether
    the run ends in an autonomous answer or a handoff acknowledgement —
    one code path, one idempotency guarantee, for both outcomes.

## Alternatives rejected

- **A second graph/engine for the "full" orchestration flow**, leaving the
  Phase 5/6 graph for simple cases — rejected; it would require re-proving
  every budget/termination guarantee for a second implementation and
  create two orchestration identities for what is conceptually one run.
- **Modeling `HumanHandoff` as a registered tool** — rejected; the master
  brief's own E2E requirement (a customer-requested handoff produces no
  `ToolExecution`) is unreachable if handoff shares the tool-call code
  path, and a tool-shaped handoff would need an artificial handler with no
  real side effect to gate through policy for no reason.
- **Letting the model's handoff request carry a workspace/assignee/role**
  and validating it server-side — rejected in favor of the request simply
  having no such field at all (`NormalizedHandoffRequest` is
  `reason_code`/`summary` only). A field that must always be
  server-overridden is a bug waiting to happen the day validation is
  forgotten; a field that doesn't exist cannot be forgotten.
- **Resetting budgets on approval resume or handoff**, reasoning that "the
  human already reviewed this turn" — rejected; a resumed run that got a
  fresh budget would let an attacker manufacture unlimited additional model
  calls by repeatedly triggering approval-requiring actions.
- **A soft/best-effort classification for provider failures** (retry
  forever, or always fail, never handoff) — rejected in favor of the
  explicit table in `failure_classification.py`: retryable-provider
  exhaustion with a conversation becomes a handoff (a human can help);
  everything else stays `FAILED` (nothing hands off due to a
  misconfiguration or a business rule correctly denying an action).

## Consequences

Benefits:

- Deterministic authorization: every side-effecting action's execution is
  provably gated by policy or a real `ApprovalDecision` — never by
  anything the model alone decided, reconfirmed under real concurrency in
  Block 6.
- Auditability: every state transition (run start, tool execution, policy
  decision, approval decision, handoff creation, cancellation) is an
  `AuditEvent`, and the safe operational trace records what happened
  without ever persisting private model reasoning.
- Retry safety: every distributed action (run claim, tool execution,
  approval resume, handoff completion) has a durable or service-enforced
  idempotency point; redelivery is provably a no-op, not a duplicate side
  effect.
- Bounded loops: a model that never voluntarily stops (repeated tool
  requests, repeated policy-denied attempts, repeated malformed calls)
  always terminates through a budget, never runs unbounded.
- Tenant isolation: RAG, tool resources, integrations, approvals, and
  handoffs are all workspace-scoped at the query layer, and a foreign
  UUID for any of them resolves to a non-leaking not-found — proven for a
  perfect-match RAG chunk specifically, the hardest case, not just for
  simple foreign-key lookups.
- Provider independence: swapping the LLM, payment, or calendar provider
  touches only that provider's typed adapter — the orchestration graph,
  policy engine, and approval/handoff lifecycle are unaware which vendor
  is behind the interface.

Trade-offs:

- Sequential tool execution caps a single turn's maximum throughput —
  a deliberate simplicity/safety trade against parallel-execution
  complexity, not a performance oversight.
- Persistent, resumable orchestration requires more state coordination
  than a request-response agent loop — the state machine, idempotency
  inventory, and concurrency test surface in this phase are all a direct
  cost of that choice.
- Approval and handoff each add a distinct terminal/pause state to
  `AgentRun`, increasing the state machine's size beyond a minimal
  success/failure model — accepted because a smaller state machine would
  have to encode the same distinctions somewhere else, less legibly.
- Not every crash boundary can atomically include external provider state:
  a refund provider call and the `ToolExecution` row that records it
  cannot commit as one atomic unit with Stripe's own state. This is
  mitigated, not eliminated, by provider-side idempotency keys and the
  resume claim's replay-safe design — a real provider-side partial failure
  during the network call itself remains a residual risk inherent to any
  system coordinating with an external service.
