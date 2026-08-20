# Deterministic Policy Engine and Human Approval Workflow

Phase 8 inserts the deterministic authorization boundary between an
AI-requested business action and its execution. It does **not** add
frontend UI, notification delivery, or evaluation/analytics — see the
[Phase 9 integration](#phase-9-integration) section for what remains.

## Architecture

```text
Agent Runtime
    |
    v
tools.execution.execute_tool          (Phase 6 — unchanged entry point)
    |
    v
registry lookup / binding / budget / typed input validation / idempotency
    |                                   (Phase 6, unchanged ordering)
    v
risk assessment + policy evaluation    (Phase 8 — runs once per ToolExecution)
    |
    +---- ALLOW ------------------> handler execution (unchanged Phase 6/7 path)
    |
    +---- DENY -------------------> BLOCKED_BY_POLICY, handler never runs
    |
    +---- REQUIRE_APPROVAL --------> ApprovalRequest created
                                      ToolExecution -> WAITING_FOR_APPROVAL
                                      AgentRun -> WAITING_FOR_APPROVAL
                                             |
                                        human decision
                                       /              \
                                  approve             reject
                                     |                   |
                                     v                   v
                          tools.execution           ToolExecution ->
                          .resume_after_approval()  APPROVAL_TERMINATED
                                     |
                          agents.runtime.graph
                          .run_resume_graph()
                                     |
                             AgentRun completes
```

There is no second execution path. `execute_tool` is still the only
function that ever invokes a tool handler — the gate runs *inside* it,
between Phase 6's idempotency claim and the handler call, exactly where
CLAUDE.md's tool-execution rules describe: "The executor validates
permissions, schemas, **policy**, timeout, idempotency, error mapping,
persistence, and output."

## Model output is never authorization

The LLM proposes a tool name and arguments. It cannot set `risk_level`,
`policy_result`, `approval_required`, `required_role`, or any other
authorization-relevant field — every business tool's Pydantic input model
uses `StrictModel` (`extra="forbid"`), so a proposed argument like
`{"policy_result": "allow"}` is rejected at Phase 6's existing input
validation step, before the gate ever runs (section 115 acceptance
scenario). Risk and policy are computed exclusively from:

- the tool's code-owned `ToolDefinition.risk_level` / `side_effect_type`
  (never client- or model-suppliable);
- the tool's own already-schema-validated arguments (e.g. `amount_minor`);
- the workspace's server-stored `PolicyVersion`/`PolicyRule` rows.

## Risk assessment

`policies.risk.assess_risk` is a pure function: `ToolDefinition` risk
metadata plus canonical arguments in, a `RiskOutcome` out. The only dynamic
adjustment is a single documented rule — a `FINANCIAL` action whose
`amount_minor` meets `POLICIES_RISK_BUMP_FINANCIAL_AMOUNT_MINOR` is
escalated by exactly one risk tier. No LLM classifier, no heuristic beyond
that one rule. Given the same inputs, the same `RiskOutcome` is always
produced.

Every assessment is persisted as an immutable `RiskAssessment` row
(one-to-one with its `ToolExecution`) — never recalculated in place. A
retried logical action gets a *new* `ToolExecution` (see
[Idempotency and the gate](#idempotency-and-the-gate-run-exactly-once)),
and therefore a new `RiskAssessment`.

## Policy model

```text
Policy (workspace-owned, named)
  -> PolicyVersion (immutable once ACTIVE)
       -> PolicyRule[] (declarative, priority-ordered)
```

- At most one `Policy` may be `active` per workspace (DB partial unique
  constraint) — that policy's active `PolicyVersion` governs every
  evaluation for the workspace.
- A `PolicyVersion`'s rules are frozen the moment it is published
  (`services.publish_policy_version`) — to change behavior, create a new
  version. A `PolicyEvaluation` references the exact version active at
  evaluation time, so historical decisions stay reproducible even after the
  workspace activates a newer version (section 118-119).
- `PolicyRule.condition_config` is a small JSON document —
  `{"all": [{"predicate": "<name>", ...params}]}` — naming server-owned
  predicate functions from `policies/predicates.py`. It is never
  executable code: no `eval`, no `exec`, no dynamic import. Configuring an
  unknown predicate name is a **fail-closed configuration error**, not a
  silently-ignored condition.

### Conflict resolution

If more than one enabled rule matches the same action, precedence is
fixed and code-owned: **DENY > REQUIRE_APPROVAL > ALLOW**. A single DENY
rule always wins regardless of rule ordering mistakes elsewhere. This is
deliberately not "first match wins" — that would make the safety of a
policy depend on the order rules happen to be listed in.

### No match / no active policy

- If a workspace has no active custom `Policy`, `policies.defaults` — a
  code-owned, non-editable fallback — governs every evaluation
  (`policy_version=None` on the resulting `PolicyEvaluation`).
- If a workspace *does* have an active policy but no rule matches the
  action, the evaluator falls back to the same code-owned default rather
  than an implicit ALLOW (`decision_code` is prefixed
  `no_matching_rule_fallback:`).

### System default policy (`policies/defaults.py`)

```text
read-only tool                          -> ALLOW
payment.refund                          -> USD threshold policy (below)
other FINANCIAL side effect             -> REQUIRE_APPROVAL
EXTERNAL_WRITE side effect              -> REQUIRE_APPROVAL
DESTRUCTIVE side effect                 -> REQUIRE_APPROVAL
INTERNAL_WRITE side effect              -> ALLOW
HIGH/CRITICAL risk, no side-effect match -> REQUIRE_APPROVAL
everything else                         -> ALLOW
```

**Refund policy** (the "at least one meaningful deterministic refund
policy" required by section 32): USD only, using
`POLICIES_DEFAULT_REFUND_AUTO_ALLOW_MAX_MINOR` (default $50.00) and
`POLICIES_DEFAULT_REFUND_APPROVAL_MAX_MINOR` (default $500.00) —

```text
amount <= auto-allow max   -> ALLOW
amount <= approval max     -> REQUIRE_APPROVAL
amount >  approval max     -> DENY
any non-USD currency       -> REQUIRE_APPROVAL (never silently applies the
                               USD threshold to an unconfigured currency)
```

A workspace can fully replace this behavior by activating its own
`Policy`/`PolicyVersion` with `payment.refund`-scoped rules.

### Fail-closed evaluation

If evaluation cannot safely complete — an unknown predicate name, a
malformed `condition_config` — the evaluator raises
`PolicyEvaluationFailedError`, and the gate always maps this to **DENY**
(`decision_code="policy_evaluation_failed"`), never to ALLOW. The
`ToolExecution` still transitions to `BLOCKED_BY_POLICY` and a
`PolicyEvaluation` row is still persisted (with `policy_version=None`) so
the failure is auditable.

## System safety floor

Workspace policy can only run **after** Phase 6's own hard safety checks
already passed: unregistered tool, unbound tool, disabled binding,
exhausted tool-call budget, and invalid typed input all raise before the
gate is ever reached. No `PolicyRule` can be configured to bypass any of
these — there is no rule-level "allow anyway" for a tool the run isn't
bound to. Similarly, `INTEGRATIONS_LIVE_PROVIDERS_ENABLED=False` still
gates every real provider adapter at the integration-services layer
regardless of what policy decides; a policy ALLOW only ever authorizes
reaching the *existing* Phase 7 execution boundary, never bypasses it.

## Idempotency and the gate run exactly once

The gate persists a `RiskAssessment` and `PolicyEvaluation` as
`OneToOneField`s on `ToolExecution`. Running the gate twice for the same
row would violate that uniqueness. `tools.execution` guarantees the gate
runs **at most once per `ToolExecution` row**:

- A brand-new idempotency-key claim (or no key at all) always gets a
  fresh row — the gate runs.
- A retry with the *same* idempotency key against a row that already
  **succeeded** replays the stored result (Phase 6 behavior, unchanged).
- A retry against a row that is `WAITING_FOR_APPROVAL` re-raises
  `approval_required` without touching the gate or creating a second
  `ApprovalRequest` — Phase 6's own idempotency identity is what prevents
  approval spam (section 11), not a second dedup mechanism.
- A retry against a row that is `BLOCKED_BY_POLICY` or
  `APPROVAL_TERMINATED` (rejected/expired) replays that stored outcome —
  it is **not** reset back to `PENDING` for a fresh gate pass, because that
  row already owns its one-to-one gate rows. An ordinary handler-level
  failure (`FAILED`/`TIMED_OUT`) is unaffected and still resets to `PENDING`
  for a normal Phase 6 retry — such a row was never through the gate, or
  reached the gate and got ALLOW, so a fresh PENDING claim on it correctly
  skips the gate the second time too (see `_already_policy_evaluated`).

All of the gate's database writes — `RiskAssessment`, `PolicyEvaluation`,
optionally `ApprovalRequest`, and the `ToolExecution` status transition —
commit as one atomic unit before any control-flow exception
(`ToolPolicyDeniedError`, `ToolApprovalRequiredError`,
`ToolPolicyEvaluationFailedError`) is raised, so a crash between "row
persisted" and "status transitioned" can never happen.

## Approval lifecycle

```text
pending -> approved -> (resume)
pending -> rejected
pending -> expired
pending -> cancelled
```

All four terminal states are reached only from `pending`; none reopen.

### One request per action, one decision per request

- `ApprovalRequest.tool_execution` is a `OneToOneField` — "one active
  approval per action" (section 11) is a database constraint, not an
  application-level check.
- `ApprovalDecision.approval_request` is a `OneToOneField` — "at most one
  final decision" (section 41) is likewise DB-enforced. A concurrent race
  to decide the same request loses on `IntegrityError`, not on a
  best-effort lock.

### RBAC and self-approval

`ApprovalRequest.required_role` is derived server-side from the action's
effective risk (`medium -> support_manager`, `high -> admin`,
`critical -> owner`) at creation time — never client-suppliable. Deciding
an approval checks the caller's **current** database membership role
(`approvals.services.role_satisfies_requirement`), never a JWT claim or a
role cached from when the approval was created — a demoted approver loses
approval authority immediately (section 50). The actor who triggered the
underlying `AgentRun` (`ApprovalRequest.requested_by`) may never decide
their own request (section 49).

### Expiry

Every `ApprovalRequest.expires_at` is set from
`POLICIES_DEFAULT_APPROVAL_TTL_SECONDS` (24h default) or a rule-specific
`approval_ttl_seconds`. Expiry is checked from the wall clock at every
read path that matters — inside `decide_approval` before any decision is
accepted, and via a 5-minute Celery beat sweep
(`expire_stale_approvals_task`) that catches requests nobody ever acted
on. Neither path trusts a stale `status` value alone.

### Cancellation

If the underlying `AgentRun` is cancelled while a `ToolExecution` sits at
`WAITING_FOR_APPROVAL`, `agents.services.cancel_agent_run` also cancels the
associated `ApprovalRequest` and finalizes the `ToolExecution` as
`CANCELLED` — a cancelled run's pending approval can never later be
approved into executing.

## Pause and resume — no busy waiting

An `AgentRun` that hits a `REQUIRE_APPROVAL` decision transitions to
`AgentRunStatus.WAITING_FOR_APPROVAL` (`agents.services._pause_run_for_approval`)
and the Celery task/worker thread that was running it simply returns —
nothing holds a thread, a Celery worker, or a database transaction open
while a human decides. All of the run's budget counters
(`model_call_count`, `step_count`, `tool_call_count`, tokens, cost) are
persisted at the moment of pause and never reset.

On approval, `approvals.services.decide_approval` schedules
`approvals.tasks.resume_approved_action_task` via
`transaction.on_commit` — never inside the HTTP request's own transaction,
and never performing the actual provider call synchronously in the
approval API request. The task calls
`agents.services.resume_agent_run_after_approval`, which:

1. Race-safely claims the run (`WAITING_FOR_APPROVAL -> RUNNING`) — a
   second/redelivered task call finds nothing to do and returns
   `"already_resumed"` (section 67-68, 90-91, 128).
2. Calls `tools.execution.resume_after_approval`, which itself
   independently, race-safely claims the `ToolExecution`
   (`WAITING_FOR_APPROVAL -> RUNNING`) before invoking the handler.
3. Continues the run's bounded LangGraph state machine from exactly the
   point Phase 6's own successful-tool-call path already routes through —
   `agents.runtime.graph.build_resume_graph` reuses every node function
   from the main graph (`check_budget`, `generate_response`,
   `execute_tool_call`, ...), entered directly at `check_budget` instead of
   `prepare_run`, with the run's *persisted* counters as the starting
   state. This is what lets a resumed run receive a real, bounded follow-up
   model turn — "Your refund has been processed." — without replaying the
   tool call or resetting any budget counter (section 153-158).

Rejection is handled synchronously and does not resume the run: the
`ToolExecution` moves to `APPROVAL_TERMINATED`
(`error_code="approval_rejected"`), and the `AgentRun` stays at
`WAITING_FOR_APPROVAL` — Phase 8 deliberately does not add advanced
rejection-recovery planning (section 70); a future phase can decide how
the agent should respond to a human "no."

## TOCTOU protection and approval reuse

`resume_after_approval` executes using the `ToolExecution`'s own stored
`arguments_redacted` snapshot — the exact arguments the policy gate
evaluated — never a fresh, model-generated argument set. There is no code
path at resume time that accepts a caller-supplied argument at all. An
approval for `refund $20` cannot be used to authorize `refund $200`
because there is no mechanism by which a different amount could ever reach
the resumed handler (section 53-55). If a future tool had a genuinely
sensitive input field, the redacted snapshot would contain a
`"***REDACTED***"` placeholder there; `resume_after_approval` re-validates
the snapshot against the tool's own Pydantic input schema before executing
and fails closed (`tool_invalid_input`) rather than silently substituting
or guessing a value. No current approval-gated tool (`payment.refund`,
`calendar.create_booking`, `notification.send`) has a sensitive input
field, so this is a documented, tested defensive path rather than an
active limitation today.

## Idempotency across the whole stack

For `payment.refund`: `ApprovalRequest` uniqueness (one per
`ToolExecution`) + Phase 6 `ToolExecution` idempotency (one row per
workspace/tool/idempotency-key) + Stripe's own native idempotency key
(`f"{tool_key}:{tool_execution_id}"`, unchanged from Phase 7) compose into
"one approved logical refund = at most one external refund", proven by
`test_duplicate_approve_clicks_cause_exactly_one_provider_refund` and the
Phase 7 ambiguous-timeout regression test, which Phase 8 does not disturb.
The same composition holds for `calendar.create_booking`.

## Tool execution states added

```text
pending -> running -> {succeeded, failed, timed_out, cancelled}   (Phase 6, unchanged)
pending -> waiting_for_approval -> running                        (approved)
pending -> waiting_for_approval -> approval_terminated             (rejected/expired)
pending -> waiting_for_approval -> cancelled                       (run/execution cancelled)
pending -> blocked_by_policy                                       (denied)
```

Only three states were added — `waiting_for_approval` (non-terminal),
`blocked_by_policy` and `approval_terminated` (both terminal). No further
state explosion: `blocked_by_policy` and `approval_terminated` are kept
distinct from Phase 6's plain `failed`/`cancelled` specifically so an
idempotency-key retry never re-enters the gate for a row that already
owns one-to-one `RiskAssessment`/`PolicyEvaluation` rows (see
[Idempotency and the gate](#idempotency-and-the-gate-run-exactly-once)).

## RBAC (API layer)

Policy configuration (`policies.permissions.CanManagePolicies`) is
owner/admin only. Approval read access (list/detail) is any active
workspace member — the response is always safe/redacted. Deciding an
approval requires only `IsWorkspaceMember` at the DRF layer; the real
authorization check (role sufficiency, self-approval) happens inside
`approvals.services.decide_approval` because both depend on the specific
`ApprovalRequest`'s `required_role`, not a static permission class.

The approve/reject API is two separate endpoints
(`/approvals/{id}/approve/`, `/approvals/{id}/reject/`) rather than one
endpoint with a `decision` body field — the decision is the endpoint you
call, never a client-suppliable value (section 116). `approved_by`,
`required_role`, `risk_level`, and every other authoritative field are
similarly absent from every request body Phase 8 accepts.

## Audit and observability

New `AuditAction` values: `policy.created`, `policy.updated`,
`policy.version_created`, `policy.version_published`, `policy.activated`,
`policy.deactivated`, `approval.requested`, `approval.approved`,
`approval.rejected`, `approval.expired`, `approval.cancelled`. New safe
`AgentStepType` trace events: `risk_assessed`, `policy_evaluated`,
`approval_requested`, `approval_approved`/`rejected`/`expired`,
`run_waiting_for_approval`, `execution_resumed`. None of these ever
contain hidden reasoning — only operational facts (tool key, decision,
risk level, error codes).

## Known limitations

- **Resume-graph model-turn scope**: the resumed run's follow-up model
  turn is a single bounded call, matching Phase 6's "one bounded tool
  round-trip" invariant — a second tool call proposed in that follow-up
  turn is itself gated by policy again (correctly), but Phase 8 does not
  add any additional multi-turn planning beyond what Phase 6 already
  supports.
- **No policy simulation/dry-run endpoint**: section 151 marks this
  optional; not implemented in Phase 8.
- **No CRM/Slack/email approval notifications**: explicitly out of scope
  (section 5) — an approver currently discovers a pending request only by
  polling the approvals API.
- **Concurrent approval-decision IntegrityError race branch** is
  implemented and reachable (`decide_approval`'s nested
  `transaction.atomic()` catches a lost `ApprovalDecision` insert race) but
  is inherently timing-dependent to force deterministically in a
  single-process test; the equivalent two-thread `decide_approval` race
  tests validate the same invariant (exactly one decision, one final
  status) end-to-end instead.

## Phase 9 integration

`payment.refund` and `calendar.create_booking` now execute *only* after a
deterministic ALLOW or a real human APPROVE — the core acceptance
criterion of Phase 8 ("high-risk AI-requested actions can no longer
execute merely because the LLM requested them") is met and regression
tested end-to-end. Frontend approval queues, richer notification
channels, and multi-agent orchestration remain future phases.
