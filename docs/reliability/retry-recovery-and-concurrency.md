# Retry, Recovery, and Concurrency Model

This document is a concise, implementation-grounded description of how
SupportPilot AI's backend behaves under concurrency, retries, and partial
failure, written as part of Phase 16 (Reliability, Coverage & Performance
Hardening). Like `docs/security/threat-model.md`, it describes what the
code actually does today — not aspirational guarantees — and calls out
residual risk explicitly rather than assuming it away. It is a living
document, extended through the rest of Phase 16 rather than written once.

## Concurrency guarantees proven this phase

Every state machine below is guarded by `select_for_update()` inside
`transaction.atomic()`, re-reading and validating the *current* database
row before writing — never trusting a Python-object status read before the
lock was acquired. Phase 16 added real-thread, real-PostgreSQL proof (not
mocked timing) for the races previously untested, and found and fixed four
genuine defects in the process:

| Domain | Races proven | Defect found | Fix |
|---|---|---|---|
| `agents` (`AgentRun`) | claim/claim, cancel/cancel, cancel/complete, resume-claim/cancel | — | — |
| `tools` (approval-resume) | concurrent/redelivered `resume_after_approval` | A concurrent resume observing another resume still in flight fell into a defensive fallback that fabricated `ToolApprovalRejectedError`, which then incorrectly failed the whole agent run | Raise the existing `ToolExecutionInProgressError` instead; the caller (`agents.services.resume_agent_run_after_approval`) treats it as a safe no-op |
| `approvals` | approve/approve, approve/reject, approve/expire, expire/reject, resume/resume | `decide_approval`'s status dispatch fell through an already-EXPIRED row into the PENDING-only branch, recording a phantom `ApprovalDecision` (a false "approved"/"rejected" audit event and webhook) even though the underlying `ToolExecution` was already terminated | Explicit `EXPIRED` branch that fails closed with `ApprovalExpiredError` and records no decision |
| `evaluations` | same run started twice, two cases finishing concurrently, cancel vs in-flight case claim | (1) `_claim_evaluation_result` locked Result→Run while `cancel_evaluation_run` locked Run→Result — a real deadlock, reproduced as a PostgreSQL `deadlock detected` error, not a timeout. (2) `completed_cases`/`passed_cases` were two sequential `.count()` queries under READ COMMITTED; a case finishing between them could drive `failed_cases` negative, tripping the `eval_run_passed_lte_completed` DB constraint — reproduced as a real `IntegrityError` under load | (1) Lock Run before Result everywhere, matching every other multi-row lock in the module. (2) Compute both counts from one conditional-aggregate query (`_aggregate_case_counts`), so both counts share one snapshot |
| `channel_ingress`, `notifications`, `webhooks` | claim expiry, claim races, delivery redelivery | — (already covered by earlier phases) | — |

Every fix above shipped with a real-thread regression test and was
stress-verified with multiple repeated full-suite runs (the evaluations fix
alone: 8 consecutive full-domain runs, 688 test executions, 0 failures)
before being committed.

## Retry model

Two genuinely different retry mechanisms exist side by side, and they are
**not** applied uniformly — this is a real, currently-undocumented
inconsistency worth knowing about rather than "fixing" by force-standardizing
every task (this phase deliberately did not do that; see Residual Risks):

- **`knowledge.tasks.ingest_knowledge_document`**: the only task that
  actually retries. It catches `RetryableIngestionError` specifically (a
  narrow, deliberately-classified transient-failure type — I/O errors,
  provider timeouts, and any genuinely unexpected exception), checks the
  attempt count against `KNOWLEDGE_INGESTION_MAX_ATTEMPTS`, and calls
  `self.retry(countdown=min(60, 2**attempt))` — capped exponential backoff.
  `PermanentIngestionError` subtypes (invalid file, unsupported type,
  malformed/encrypted PDF, no extractable text, chunking/embedding
  failures) are caught *inside* `run_ingestion` itself and marked `FAILED`
  directly — they never reach the task boundary as an exception at all, so
  they are never retried.
- **`agents.tasks.execute_agent_run_task`, `approvals.tasks.resume_approved_action_task`,
  `evaluations.tasks.start_evaluation_run_task` / `execute_evaluation_case_task`,
  `channel_ingress.tasks.process_inbound_channel_event_task`**: all declare
  `max_retries=3` at the `@shared_task` decorator, but **no task body calls
  `self.retry()` or declares `autoretry_for`** — this configuration is
  currently inert. An unhandled exception in any of these fails the task
  outright with no automatic retry.

Webhook delivery retryability is classified separately and correctly at the
HTTP-response layer: `webhooks.classification.classify_http_status` treats
408/425/429 and 5xx as retryable, everything else (most 4xx) as terminal —
this governs `notifications`' own delivery-attempt scheduling, not Celery's
task-level retry.

## Idempotency and claim model

Every claim-then-process boundary follows the same shape: an atomic
`SELECT ... FOR UPDATE` that only transitions a row out of its initial
state once, returning `None`/no-op for a second caller. This makes
redelivery of the *same* logical task always safe, independent of whatever
retry mechanism (or manual redispatch) triggered it:

- `agents.services.claim_agent_run` / `_claim_run_for_resume`
- `tools.execution._claim_execution` / `_claim_resume`
- `approvals.services.decide_approval` (one-decision-per-request via a
  `OneToOneField` DB constraint, not just an application check)
- `evaluations.services.claim_evaluation_run` / `_claim_evaluation_result`
- `channel_ingress.services.claim_inbound_channel_event`
- `notifications`/`webhooks` delivery claim-and-lease (pre-existing from
  earlier phases)

## Recovery/sweeper model

Two domains have an explicit periodic sweeper that re-publishes work whose
original dispatch was lost (a `transaction.on_commit` publish that never
reached the broker, e.g. a broker outage at the moment of commit):

- `notifications.recovery` — due-delivery dispatch and expired-claim
  recovery, proven idempotent (including racing recovery workers and stale-
  worker-cannot-overwrite-newer-completion) in earlier phases.
- `channel_ingress.recovery.recover_stuck_inbound_events` — re-publishes
  `RECEIVED` events past a staleness threshold. Phase 16 added end-to-end
  proof that (a) a second sweep after the real claim boundary has actually
  processed the event is a true no-op (no second dispatch), and (b) two
  sweeps racing ahead of any worker may legitimately double-publish (an
  honest at-least-once republish), but the claim boundary still lets only
  one of the two redelivered tasks actually claim and process the event.

`approvals.services.expire_stale_approvals` is a periodic sweep with the
same single-fire-per-row contract, proven this phase to be a true no-op on
a second invocation (no duplicate `AuditEvent`).

## At-least-once boundaries (never exactly-once)

- Webhook/notification delivery is at-least-once at the transport level;
  downstream idempotency (where the receiving system supports it) is what
  actually prevents a duplicate *effect*, not this system's own delivery
  guarantee.
- A sweep re-publishing an event/delivery id is itself at-least-once — the
  sweep never claims anything on its own; only the underlying
  claim-then-process boundary is the single point of correctness.
- No claim in this system is exactly-once across process/worker boundaries
  by construction; it is "at most one caller's *effect* survives," enforced
  by row locks and DB constraints, which is a different and weaker
  (correctly weaker) guarantee than "the message was delivered exactly
  once."

## Residual risks

- **No stuck-run recovery sweeper for `agents`, `approvals`, or
  `evaluations`.** Unlike `channel_ingress` and `notifications`,
  nothing periodically finds an `AgentRun`/`EvaluationRun`/`EvaluationResult`
  left `RUNNING` by a worker that crashed mid-execution. Combined with
  `CELERY_TASK_ACKS_LATE` not being configured (Celery's default is to
  acknowledge a task *before* execution, so the broker does not redeliver
  it after a worker crash) and the `max_retries=3` on these tasks being
  inert (see Retry model above), a mid-execution worker crash on one of
  these five tasks currently leaves the row stuck with no automated
  recovery path — only a manual operator intervention. This is a real gap,
  not a hypothetical one, but closing it (a staleness threshold, a decision
  between re-executing vs. failing the row, a new periodic sweep mirroring
  the `channel_ingress`/`notifications` pattern) is a genuine feature
  addition with real design decisions attached, not a narrow concurrency
  fix — deliberately left undone this phase rather than absorbed silently,
  and flagged here for explicit prioritization.
- **Retry configuration is not uniform across tasks**, as described above.
  Standardizing it was deliberately not done this phase without a decision
  on what each task's correct transient-failure classification actually is
  (unlike `knowledge`'s already-narrow `RetryableIngestionError` split).
- Celery Beat scheduling/packaging for the periodic sweepers
  (`expire_stale_approvals_task`, `recover_stuck_inbound_events_task`,
  the `notifications` due-delivery/expired-claim sweeps) is a Phase 17
  deployment-packaging concern, out of scope here.
- Single-node Docker Compose PostgreSQL/Redis topology (development/demo
  scale) has not been load-tested at internet scale; this phase's
  concurrency proofs establish *correctness* under real concurrent access,
  not throughput ceilings.
