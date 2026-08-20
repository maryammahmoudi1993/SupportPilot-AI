# ADR 0006: Deterministic Policy Evaluation and Immutable Approval Snapshots

- Status: Accepted
- Date: 2026-08-20

## Context

Phases 5-7 gave the agent runtime a bounded execution loop, a trusted typed
tool registry, and real business integrations — but nothing yet stood
between "the LLM proposed `payment.refund`" and "the refund executed."
Phase 8 has to add that boundary without becoming the thing it's supposed
to prevent: a policy engine an LLM could talk its way around, an approval
system that races itself into a double refund, or a "fake human approval"
that defeats the point of requiring one.

## Decision

1. **The policy gate is inside `tools.execution.execute_tool`, not a
   parallel entry point.** No `execute_policy_tool()`,
   `execute_approved_tool_directly()`, or similar. The gate runs between
   Phase 6's existing idempotency claim and the handler call — CLAUDE.md
   already lists "policy" among what the executor validates, alongside
   permissions, schemas, timeout, and idempotency; Phase 8 fills in that
   one item rather than inventing a second boundary next to it.
2. **Risk and policy are computed only from server-owned inputs.** The
   tool's code-owned `ToolDefinition.risk_level`/`side_effect_type` and its
   own already-schema-validated (`StrictModel`, `extra="forbid"`)
   arguments. A model-proposed `{"policy_result": "allow"}` argument is
   rejected by the tool's own input schema before the gate is ever reached
   — there is no field anywhere in the request path an LLM could set that
   the gate would trust.
3. **Exactly three decisions, fixed precedence.** `ALLOW`/`DENY`/
   `REQUIRE_APPROVAL` — no `maybe`, no confidence score. When multiple
   rules match, `DENY > REQUIRE_APPROVAL > ALLOW` is the only precedence:
   fixed and code-owned, not a per-policy configuration option, so a
   misordered rule list can never accidentally weaken a workspace's
   security posture.
4. **A constrained predicate registry, not a rule language.** `PolicyRule
   .condition_config` names server-owned functions from
   `policies/predicates.py` by string key; the database configures
   *parameters*, never *behavior*. This mirrors `tools.registry` exactly —
   the same pattern ADR 0004 already established for tool dispatch. An
   unrecognized predicate name is a configuration error
   (`PolicyEvaluationFailedError`), not a silently-skipped condition.
5. **Fail closed, always.** Any evaluation that cannot safely complete
   (unknown predicate, malformed `condition_config`) resolves to `DENY`,
   never `ALLOW`. This is enforced at exactly one place —
   `_run_policy_gate`'s single `except PolicyEvaluationFailedError` branch
   — so there is no second, forgettable code path that could default the
   other way.
6. **Policy versions are immutable once active; approvals reference the
   exact version they were judged against.** Publishing a `PolicyVersion`
   freezes its rules; changing behavior means creating a new version.
   `PolicyEvaluation.policy_version` is a real foreign key (`PROTECT`), so
   a workspace activating v4 while an approval created under v3 is still
   pending never silently changes what that pending approval means.
7. **"One active approval per action" and "one final decision" are
   database constraints, reusing identity Phase 6 already established.**
   `ApprovalRequest.tool_execution` and `ApprovalDecision.approval_request`
   are both `OneToOneField`s. Phase 6's own idempotency claim already
   defines "same logical action" (workspace + tool + idempotency key +
   argument fingerprint); Phase 8 does not build a second identity concept
   next to it — a repeated model/tool attempt for the same action reaches
   the *same* `ToolExecution` row, and therefore can only ever have one
   `ApprovalRequest`.
8. **Resume executes the stored snapshot, never a fresh argument.**
   `tools.execution.resume_after_approval` reconstructs the handler's
   arguments from `ToolExecution.arguments_redacted` — the exact,
   already-validated arguments the policy gate evaluated — and there is no
   parameter anywhere in the resume path through which a different
   argument set could reach the handler. An approval for `refund $20`
   structurally cannot be reused to authorize `refund $200`; there is no
   code path where the $200 could enter.
9. **Pause and resume reuse the bounded LangGraph state machine, entered
   at a different node — not a second graph implementation.**
   `agents.runtime.graph.build_resume_graph` wires the *same* node
   functions (`check_budget`, `generate_response`, `execute_tool_call`,
   ...) with a different entry edge (`check_budget` instead of
   `prepare_run`), started from the run's own persisted counters. The
   run's budget/termination guarantees (Phase 5/6) therefore extend to the
   post-approval continuation for free, rather than needing to be
   re-proven for a bespoke "resume executor."
10. **RBAC for a decision is re-derived from current DB membership at
    decision time, never cached.** `approvals.services.decide_approval`
    reads the caller's live `WorkspaceMembership.role`; a demoted approver
    loses decision authority immediately, matching the same pattern
    `workspaces/permissions.py` already uses everywhere else in the
    codebase for exactly this reason.

## Alternatives rejected

- **A generic rule-expression language (Python/JS snippets, SQL
  fragments) for `condition_config`** — rejected outright; this is the
  same "arbitrary execution surface" shape ADR 0004 rejected for tools and
  the master brief explicitly prohibits (`eval`/`exec`, user-provided
  executable conditions).
- **A second idempotency/dedup table for approvals** — rejected; Phase 6's
  `ToolExecution` idempotency identity already answers "is this the same
  logical action," and building a parallel concept next to it would create
  two sources of truth that could disagree.
- **Replaying the full agent-run graph from `START` on resume** —
  considered and rejected: re-invoking `generate_response` a second time
  for the *same* turn would inflate `model_call_count` for a step that
  already happened, directly violating the "waiting must never reset a
  budget counter" requirement. Entering the existing graph at
  `check_budget` with persisted counters avoids this without needing a
  bespoke resume state machine.
- **Optimistic execution ("run the handler, ask forgiveness")** for
  `REQUIRE_APPROVAL` — rejected; the handler is provably never invoked
  before approval (`fake.refund_call_count == 0` is asserted end-to-end),
  which is the entire point of the gate.
- **A soft/advisory policy mode that logs but doesn't block** — rejected;
  every `REQUIRE_APPROVAL`/`DENY` decision is enforced unconditionally.
  There is no configuration flag that turns the gate into a no-op, because
  such a flag would itself become the thing an attacker (or a careless
  operator) targets.

## Consequences

Benefits:

- `payment.refund` and `calendar.create_booking` are provably gated:
  regression tests assert the provider is called zero times under DENY
  and REQUIRE_APPROVAL-pending, and exactly once under ALLOW or approved
  REQUIRE_APPROVAL, including under duplicate-approve-click and
  duplicate-Celery-delivery races.
- Extending policy to a new predicate or a new tool's risk metadata never
  touches `tools/execution.py`'s gate wiring — only
  `policies/predicates.py` (a new registered function) or the tool's own
  `ToolSpec.risk_level`.
- The system default policy means a workspace gets safe, non-trivial
  behavior (including a real refund threshold) with zero configuration —
  "must not require every workspace to configure policy before read-only
  tools work" (section 122) — while side-effecting tools are never
  silently unrestricted.

Trade-offs:

- The resumed run's follow-up model turn is bounded to what Phase 6's
  graph already supports (one further tool call, itself re-gated) — Phase
  8 does not add multi-step replanning after a human decision.
- No approval-notification channel (email/Slack/webhook) exists yet; an
  approver must poll the approvals API. Explicitly deferred per the master
  brief's scope boundary.
- `BLOCKED_BY_POLICY` and `APPROVAL_TERMINATED` are two additional
  terminal `ToolExecutionStatus` values beyond Phase 6's four — an
  intentional, documented exception to "don't create unnecessary state
  explosion," required specifically so an idempotency-key retry against a
  policy-gated row never re-enters the gate and collides with its own
  one-to-one `RiskAssessment`/`PolicyEvaluation` rows.
