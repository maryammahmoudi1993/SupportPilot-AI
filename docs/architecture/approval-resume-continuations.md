# Approval Resume Completion and Decision Continuations

Phase 9 Block 4 completes the approval pause/resume branch `bounded-tool-orchestration.md`
deliberately left open: an `AgentRun` paused in `WAITING_FOR_APPROVAL` now always reaches a
terminal, single-message outcome, for every human decision and for expiry, without ever
becoming a second run or a replay of the original customer request.

## One continuation entry point for every outcome

`agents.services.resume_agent_run_after_approval` is the single resume entry point for all four
decision outcomes. `approvals.services.decide_approval` (for approve/reject) and
`expire_stale_approvals`/`_expire_if_stale` (for expiry) all dispatch the same
`resume_approved_action_task` via `transaction.on_commit` — the continuation itself branches on
the `ApprovalRequest.status` that decision just persisted, so there is exactly one resume-claim
mechanism (`_claim_run_for_resume`, `WAITING_FOR_APPROVAL -> RUNNING`) guarding all of them, not
one path per outcome. A cancelled approval is the one status that dispatches nothing to continue:
`cancel_agent_run` already terminates the run itself in the same transaction that cancels the
approval, so there is nothing left to resume to the LLM.

* **Approved** — `tools.execution.resume_after_approval` executes the one frozen `ToolExecution`
  the approval references, using the stored redacted argument snapshot, never a fresh
  model-generated one. Its result is wrapped through the same `ToolResultContext` untrusted-data
  envelope the ordinary ALLOW path uses (`TOOL RESULT — UNTRUSTED EXTERNAL DATA` / `END TOOL
  RESULT`) — a human approving the *action* grants its *data* no special trust.
* **Rejected** / **Expired** — no handler is ever invoked. The continuation builds a safe,
  structured `ToolResultContext(status="denied", error_code="approval_rejected" |
  "approval_expired")` directly, with no `ToolExecution` row touched a second time. The
  approver's `ApprovalDecision.safe_comment` never enters this message — only the stable
  outcome code does.
* **Cancelled** — `resume_agent_run_after_approval` returns `"skipped"`; the run stays
  `CANCELLED`, a terminal status that never reopens.

Every branch re-enters the bounded graph at `run_resume_graph`/`check_budget` — never
`prepare_run`, never a fresh `call_llm` for the original request. `resume_state_after_tool`
reconstructs the graph's state purely from the run's own persisted counters (`model_call_count`,
`step_count`, tokens, cost), so budgets consumed before the pause are never reset and the same
`AgentRun.id`, `AgentVersion`, `trigger_message`, and `ToolExecution` continue unchanged.

## Frozen-action verification

`resume_after_approval` re-checks the `ToolExecution.arguments_fingerprint` against the
`ApprovalRequest.arguments_fingerprint` recorded at approval-request time before invoking a
handler. No application code path ever rewrites a `WAITING_FOR_APPROVAL` row's fingerprint, so
this only ever fires against direct data tampering; a mismatch fails closed
(`approval_action_changed`) with zero handler/provider calls rather than attempting to repair or
guess the intended argument. This sits alongside the pre-existing hard-safety rechecks the resume
path already performed: disabled `ToolBinding`, unregistered/inactive tool, and (transitively,
through the ordinary provider-resolution path) a disabled `IntegrationConnection`.

## Approve-vs-cancel race safety

`cancel_agent_run`'s pending-approval cleanup now cancels each `WAITING_FOR_APPROVAL`
`ToolExecution` with a conditional `UPDATE ... WHERE status = 'waiting_for_approval'` rather than
an unconditional overwrite. A concurrent approve-resume that has already claimed the row
(`RUNNING`, or further along to `SUCCEEDED`) can never be clobbered back to `CANCELLED` by a
racing cancellation — an external side effect that has already legitimately executed is never
retroactively hidden. `_claim_run_for_resume`'s own `WAITING_FOR_APPROVAL`-only guard is the
other half of this: once `cancel_agent_run` has moved the run itself to `CANCELLED`, no
concurrent or redelivered resume can claim it at all.

## Not rebuilt on resume

Consistent with Block 2's "retrieval is not re-run" principle, resuming an approval never
reissues tenant-scoped RAG retrieval or reconstructs the original conversation-context message
list — doing so could change what a subsequent model turn is grounded in after a human has
already acted on the frozen action it approved. The follow-up model turn instead sees the
run's system prompt plus the safe tool-result/outcome message described above; the original
run's RAG citations are not reattached to a post-approval final response.
