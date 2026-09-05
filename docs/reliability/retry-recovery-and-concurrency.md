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

**Phase 16 Checkpoint 2** closed the `agents`/`evaluations` half of the gap
flagged below: `agents.recovery.recover_stuck_agent_runs` and
`evaluations.recovery.recover_stuck_evaluation_runs`. Unlike the two
sweepers above — which re-publish an *unclaimed* id into an existing
claim-then-process boundary — these recover by **failing**, never by
re-dispatching: a `RUNNING` row's worker may already have called a tool
with a real side effect (a refund, a booking) before it crashed, and
silently re-executing the same run has no idempotency boundary to catch a
duplicate. Both sweeps identify rows `RUNNING` past a staleness threshold
(`AGENTS_STUCK_RUN_STALE_SECONDS` / `EVALUATIONS_STUCK_RUN_STALE_SECONDS`,
approximating "no worker progress" via `updated_at` — no per-run
heartbeat/lease exists yet) and, under the same lock-then-recheck pattern
as every other claim boundary in this codebase, transition the row to a
terminal, distinctly-labelled failure outcome (`stuck_worker_recovered` /
`EvaluationFailureCode.WORKER_CRASH_RECOVERED`). `agents`' sweep also fails
any still in-flight child `ToolExecution`; `evaluations`' sweep fails any
still-`RUNNING` case belonging to the stuck run, then recomputes and (if
now complete) finalizes the run via the existing
`_aggregate_case_counts`/`finalize_evaluation_run` — no second
implementation of that arithmetic. Both are proven idempotent, race-safe
against a still-active worker (re-checking `status`/`updated_at` after the
lock is acquired), and incapable of regressing an already-recovered row
(see `agents/tests/test_recovery.py`, `evaluations/tests/test_recovery.py`).

**Phase 16 Checkpoint 3 (Part A) closed a real false-recovery defect in the
`evaluations` sweep.** `EvaluationRun.updated_at` only advances at claim time
and again whenever *any* case *completes* (`_record_case_completion` saves
the run row) — never while a case is merely still executing. A multi-case
run, run through limited worker concurrency, can therefore legitimately go
longer than `EVALUATIONS_STUCK_RUN_STALE_SECONDS` between case completions
purely because the currently in-flight case hasn't finished yet — the run's
own timestamp going stale is not, by itself, evidence the run is dead.
Before this checkpoint, `_recover_one_stuck_run` computed this correctly at
the *case* level (only individually-stale `RUNNING` cases were ever failed)
but still unconditionally counted the sweep as a "recovery" and re-saved the
run row whenever the *run's* own `updated_at` was stale, even when a live,
non-stale case was found and nothing was actually wrong — a healthy,
actively-progressing run was never mis-failed, but it was misreported as
"recovered" and given an unnecessary write on every sweep cycle it happened
to be examined during. Fixed by checking for at least one non-terminal case
whose own `updated_at` is not stale before treating the run as a genuine
candidate: if one exists, the sweep leaves the run completely untouched and
does not count it. This uses the case's own already-existing `updated_at`
(touched at claim and at completion) as the liveness signal — no new
heartbeat mechanism was added, matching this checkpoint's "prefer existing
child-case progress over a synthetic heartbeat" guidance. See
`evaluations/tests/test_recovery.py`'s matrix (stale-with-live-case,
single-case stale-parent/live-case, race-favors-progress, all-stale,
recovered-run-cannot-regress) for the regression proof.

**Recovery primitive exists: YES** for `agents` and `evaluations`.
**Automatic periodic scheduling exists: NO** — nothing calls either sweep
function on a schedule yet; see Residual risks below for the Phase 17
boundary. `approvals` needed no equivalent: its only "worker disappears"
exposure is `ApprovalRequest` sitting `PENDING` past its TTL, which
`expire_stale_approvals` (existing, scheduled-in-Phase-17 like the others)
already covers — there is no separate `approvals`-owned `RUNNING` state a
crashed worker could strand.

**External side-effect window (Phase 16 Checkpoint 2A, section 15) — read
carefully, this is a real, named gap, not a solved problem.** What the
lock-then-recheck fencing above actually proves is narrower than "recovery
is safe": it proves the *database record* cannot regress — the old
worker's own eventual `_finalize_success`/`_finalize_failure` call
re-locks the `ToolExecution` row, sees it is no longer `RUNNING` (recovery
already moved it to `FAILED`), and no-ops instead of overwriting the
recovered state. **It does not prove, and must not be read as proving,
that the external action itself never happened.** The sequence this cannot
prevent: the old worker's in-flight provider call (e.g. `payment.refund`)
actually succeeds at the provider *after* the sweeper has already declared
the row stale and marked it `FAILED`; the old worker's own finalize
attempt then correctly no-ops (per the fencing above), but the system's
own record now permanently disagrees with reality — it believes the
refund failed when it actually went through. This is not new to recovery
and not a defect recovery introduces: it is the same "response lost after
the request already succeeded" ambiguity that exists for *any* tool call
whose network response never makes it back (a timeout, a dropped
connection, or — now — a crash detected by the sweeper), and no
reconciliation job (checking the provider's own records against ours)
exists anywhere in this codebase today for that broader category, not just
for recovery's slice of it. What recovery does *not* add on top of that
pre-existing ambiguity: recovery itself never redispatches or retries the
side-effecting call — only failing, never re-executing — so recovery is
not itself a new source of a *duplicate* side effect. Whether a *later,
independent* retry of the same logical action (an operator or a fresh
run reissuing the same refund) risks a real duplicate then depends
entirely on that specific tool/provider's own idempotency behavior: for
`payment.refund` specifically, both the fake provider and the real
`integrations.providers.stripe_provider` adapter forward the tool's
`idempotency_key` to the provider itself (Stripe's own idempotency-key
support), so a retry reusing the *same* key is provider-side deduplicated
— but this was verified only for this one tool as an existence proof, not
audited across every registered tool, and it only helps if the retry
actually reuses the same key. Building a general side-effect
reconciliation mechanism is a genuine, cross-cutting feature addition with
real design decisions attached (what "checking the provider's own record"
even means per provider), deliberately out of this checkpoint's "smallest
reliable primitive" scope — flagged here explicitly rather than silently
assumed away.

## Failure injection / provider-idempotency audit (Phase 16 Checkpoint 3, Part D)

Every side-effecting tool's idempotency key is derived deterministically
from `context.tool_execution_id` (`integrations/tools.py`:
`f"payment.refund:{context.tool_execution_id}"`,
`f"calendar.create_booking:{context.tool_execution_id}"`) — **stable across
every retry of the same logical `ToolExecution` row**, whether that retry is
the tool executor's own automatic loop (`RetryPolicy(max_retries=2, ...)`)
or a caller (agent/operator) manually re-invoking the same tool call with
the same application-level idempotency key. This is the mechanism, not a
per-scenario coincidence.

- **`payment.refund` (Stripe)**: real, provider-native idempotency —
  `integrations.providers.stripe_provider.refund_payment` forwards the key
  via Stripe's own `options={"idempotency_key": ...}`. The
  provider-succeeds-but-response-lost window (a timeout after the refund
  actually processed) is already proven closed by pre-existing tests
  exercising the fake's `committed_before_raising=True` scenario —
  `integrations/tests/test_tools_payment.py::TestPaymentRefund::test_ambiguous_timeout_does_not_double_refund_on_manual_retry`
  and `::test_repeated_call_with_same_tool_execution_reuses_the_provider_refund`:
  a transient failure that the fake models as "provider committed the
  refund before raising" is followed by a retry (same idempotency key) that
  returns the already-committed refund with **zero additional provider-visible
  refund calls**. **Duplicate refund: BLOCKED**, for retries that reuse the
  same key (the only path this system's own retry/resume machinery ever
  takes).
- **`calendar.create_booking` (Google Calendar)**: **no native
  provider idempotency** — `integrations/providers/google_calendar.py`'s own
  comment states it plainly: "Google has no native application-idempotency-key
  concept for `events.insert`." The real adapter stores the key as an
  `extendedProperties` field on the created event purely for **later,
  manual reconciliation** (detecting a duplicate after the fact by
  querying for it), not for **preventing** one. This is a real, structural
  difference from `payment.refund` that the test suite's `FakeCalendarProvider`
  (which *does* dedupe by key in-memory, matching `FakePaymentProvider`'s
  shape for symmetry/simplicity) does not itself reveal — the fake is more
  forgiving than the real provider here, which was a genuine masked defect
  until Checkpoint 4 (see below): the old version of this file's own test
  (`integrations/tests/test_tools_calendar.py`) asserted a manual retry
  after an ambiguous timeout *succeeded silently*, relying on that same
  forgiving fake, which does not reflect the real provider's behavior.
- **Notifications/webhooks**: delivery is at-least-once at the transport
  layer (see below) — a provider/network send can succeed while this
  system's own local delivery-record finalize is lost (crash, DB error),
  and the claim-then-process boundary's own retry will then re-attempt the
  *send*, not just the bookkeeping. **Duplicate network delivery: POSSIBLE**,
  by construction of at-least-once semantics — this is not "fixed" here
  because it cannot be, without the receiving system's own idempotent
  handling (e.g. a webhook HMAC/event-id dedupe on the receiver), which is
  outside this codebase's control. This was already true before this
  checkpoint and remains explicitly documented rather than silently
  assumed away.

## Calendar ambiguous-outcome fix (Phase 16 Checkpoint 4, Part A)

The Checkpoint 3 residual above ("duplicate booking residual risk: YES")
covered only *manual* retry. Investigation this checkpoint traced the exact
retry path a same-key retry takes: automatic in-process retry, manual/
operator retry, agent-driven retry, and Celery task redelivery all funnel
through the *same* function, `tools.execution._resolve_existing`, because
they all reuse the same idempotency key against the same `ToolExecution`
row. That function's generic "ordinary terminal failure: reset to PENDING
and re-invoke the handler" path previously treated an ambiguous outcome
(a timeout, or the executor's own wall-clock cutoff) identically to a
known-safe-to-retry one — silently making a second real Google Calendar
call with no way to know the first had already succeeded.

**Fix**: `RetryPolicy` gained a new field, `ambiguous_outcome_error_codes`
— error codes that, when found as a prior attempt's stored outcome, refuse
*any* further retry (automatic, manual, or task redelivery) with a new
`ToolAmbiguousOutcomeRequiresReconciliationError`, instead of resetting to
PENDING. Empty by default — every existing tool, including `payment.refund`,
is unaffected. Assigned to `calendar.create_booking` for
`integration_timeout`, `integration_malformed_response`, and the executor's
own `tool_timeout` — all three leave Google's actual commit outcome unknown.

**What this closes**: the backend's own retry/redelivery machinery can no
longer automatically issue a second `events.insert` call for the same
logical booking after an ambiguous failure — proven for automatic retry,
manual/operator retry, and task redelivery (the last two are the same code
path as the fix, so one test matrix covers both; see
`integrations/tests/test_tools_calendar.py::TestCreateBooking`).

**What remains a real, named residual — MANUAL RESIDUAL RISK, not
"automatic retry-safe"**: nothing reconciles the *true* provider-side
outcome. An operator who, believing the booking failed, issues a genuinely
*new* request (a fresh idempotency key — a different `ToolExecution`, e.g.
the agent trying again on a later turn, or a human manually re-submitting)
can still create a real duplicate event; the fix only prevents the
backend's own machinery from doing this to itself automatically.
`integrations/providers/google_calendar.py` has no `list`/`search` method
today — no existing primitive to look up a possibly-already-created event
by its stored `extendedProperties` key — so building real reconciliation
(a pre-insert existence check, itself racy without a provider-side unique
constraint) is a genuine feature addition, deliberately out of scope this
checkpoint, not attempted.

## Measured local benchmarks (Phase 16 Checkpoint 4, Part C)

**Caveat, read before any number below**: single dev machine, Docker
Compose PostgreSQL 16, warm Django test process, deterministic fakes, no
network calls. These are not a production SLA and must never be quoted as
one — they exist to catch structural regressions (query growth, unbounded
fetches), not to characterize production latency.

- **Representative API list endpoints** (customer, conversation, agent
  run, evaluation result, webchat message history — 61 seeded rows each,
  40 timed iterations after 1 warmup): 3–5 queries per request across the
  board, median 9.5–16.6ms, p95 19.7–35.5ms. No endpoint showed unbounded
  query growth.
- **Query-growth regression** (customer list at 1/10/50 rows): query count
  held constant (4 queries) at every size — reconfirms Checkpoint 2's
  finding; no regression.
- **Agent context benchmark** (`build_conversation_context`, configured
  `max_messages=20`, conversation sizes 31/301/3001 messages): rows
  fetched and query count (2) were identical at every conversation size —
  cost is bounded by the configured context limit, not conversation size,
  confirming the Checkpoint 2 query-bound fix holds at 100x scale. This is
  a structural property, not a claim of constant wall-clock latency at
  arbitrary scale.
- **Recovery sweep benchmark** (5,000 synthetic rows per table, 25 stale
  candidates, real PostgreSQL `EXPLAIN`): both `AgentRun` and
  `EvaluationRun` sweep queries used their Checkpoint 2 indexes
  (`agent_run_status_updated_idx` via an Index Scan;
  `eval_run_status_updated_idx` via a Bitmap Index Scan) — reconfirmed at a
  reproducible scale, not requiring the full 300k/150k-row experiment
  again. Total sweep cost scales with the *candidate* count (the rows
  actually recovered), not the total table size, by construction of the
  per-row lock-then-process loop.

## Worker restart and stuck-run recovery drill (Phase 16 Checkpoint 4, Part E)

Exercised against the actual Checkpoint 4 production image (built from
feature HEAD, non-root, real PostgreSQL/Redis via Docker Compose, no live
provider calls) rather than the pytest suite, to prove the drill holds
outside the test harness:

- **Worker restart**: created a `RUNNING` `AgentRun` with a backdated
  `updated_at` (simulating a crashed worker), stopped and restarted the
  Celery worker container, then invoked `recover_stuck_agent_runs()`
  explicitly (Phase 17 still owns Beat scheduling — this checkpoint
  invokes the primitive directly, not via a scheduled task). Result:
  correct bounded terminal state (`FAILED`/`stuck_worker_recovered`), no
  duplicate side effect, second sweep a safe no-op, the new
  `supportpilot_stuck_run_recoveries_total{domain="agent"}` metric
  incremented in the same process that ran the sweep.
- **Agent recovery smoke** (stale / recent / terminal / double-sweep /
  metric): all five PASS against the real image.
- **Evaluation recovery smoke** (A: stale no-progress → recovered; B:
  stale parent + live/recent child → untouched; C: all child work stale →
  recovered; D: second sweep → safe): all four PASS against the real
  image, reconfirming the Checkpoint 3 false-positive fix under
  production-like conditions, not just the test suite.

## Redis / PostgreSQL interruption drills (Phase 16 Checkpoint 4, Parts F/G)

Both drills stopped the real container, hit the live endpoints, restored
the container, and re-verified — no destructive corruption testing.

- **Redis down**: `/health/` stayed `200 healthy` (liveness contract
  correctly independent of the cache/broker); `/ready/` correctly returned
  `503 not_ready`; a cache-backed throttled endpoint (login) failed closed
  with `503 {"error":{"code":"service_unavailable", ...}}` — no raw Redis
  exception/connection string in the response body (this is
  `common.throttling.SafeScopedRateThrottle`, pre-existing from Phase 14,
  reconfirmed here under a real outage rather than a mock). **Redis
  restored**: `/ready/` recovered to `200` immediately, no web container
  restart required, and the previously-503'd endpoint resumed normal
  DRF-level responses on the next request.
- **PostgreSQL down**: `/health/` stayed `200 healthy`; `/ready/` correctly
  returned `503 not_ready`; a public DB-touching endpoint (webchat message
  history with a bogus session token) failed as a generic `500
  {"error":{"code":"internal_server_error", ...}}` — no DSN, password, or
  raw `OperationalError` in the response body. The Celery worker container
  stayed alive and logged a clean `OperationalError` for a task dispatched
  during the outage (no query ever reached the DB, so no partial-write
  risk) rather than crashing or looping. **PostgreSQL restored**:
  `/ready/` recovered to `200`, the same public endpoint resumed normal
  (`400 session_invalid`, not a 500) DB-backed responses, and a freshly
  dispatched task was picked up and processed by the *same*, still-running
  worker process — no manual data repair, no worker restart needed.

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

## Ordering determinism

`Message` rows are ordered `(created_at, sequence)` — `sequence` is a real
PostgreSQL-assigned, strictly-increasing insertion counter (see
`conversations/models.py`), not the row's UUID primary key. This closed a
real, reproduced defect: a `created_at` timestamp tie between two messages
previously fell back to sorting by `id` (a random UUID with zero
correlation to creation order), which could invert
`agents.context.build_conversation_context`'s "newest history is retained"
guarantee — the older of two same-instant messages could survive a
context-window trim while the newer one was silently dropped. This is the
deterministic root cause behind the historically-observed flake in
`agents/tests/test_context.py::test_newest_history_is_retained_...`; a
dedicated regression test now forces the exact tie condition and is
stress-verified clean. The same random-UUID-as-tiebreaker pattern
(`.order_by("-created_at", "-id")`) exists in several list-display
selectors elsewhere (`agents/selectors.py`, `channel_ingress/selectors.py`,
`conversations/selectors.py`'s own list ordering) — those were left
unchanged because relative order among same-instant rows in a paginated
list view carries no tested product guarantee, unlike conversation
history feeding an LLM's context window. Worth a broader audit if a
similar guarantee is ever built on top of one of those orderings.

**Sequence column design (Phase 16 Checkpoint 2 Part B audit).**
`Message.sequence` is a `BigIntegerField(unique=True, editable=False,
db_default=Func(Value("conversations_message_sequence_seq"),
function="nextval"))` backed by an explicitly-created PostgreSQL `SEQUENCE`
(migration `conversations/0003`) — the database assigns the value on every
`INSERT` via `nextval()`, exactly like a `BIGSERIAL` column would, never
`MAX(sequence) + 1` in application code (which would reintroduce the exact
race this column exists to close). The sequence is **global** (shared
across every workspace/conversation), not per-workspace or
per-conversation: a single monotonic counter is trivially also monotonic
within any subset of its values, so global scope loses nothing for the
actual semantic requirement ("chronological order within one
conversation") while avoiding a second per-conversation counter table.
Verified this checkpoint:

- **Fresh migration** (zero → latest on an empty database): PASS.
- **Upgrade migration with pre-existing rows**: PASS in the narrow sense
  that follows from `sequence`'s own `UNIQUE` constraint — migration `0003`
  cannot complete without giving every pre-existing row a distinct value,
  and it did (verified: five rows sharing one `created_at` came out with
  five distinct sequential values). **Correction (Phase 16 Checkpoint 2A):
  the backfill order those values landed in — PostgreSQL's physical
  heap-scan order during the `ADD COLUMN`-with-volatile-default table
  rewrite — is an implementation detail of how that one-time rewrite
  happened to execute, never a semantic chronology contract.** It is not
  claimed, and must not be read, as "PostgreSQL preserved true insertion
  order." Two genuinely different populations exist and only one of them
  has a real ordering guarantee:
  - **Rows inserted after migration `0003`**: `sequence` is DB-assigned via
    `nextval()` at INSERT time — monotonic, concurrent-safe, and
    deterministic by construction. This is a real guarantee.
  - **Rows that already existed when migration `0003` ran**: for any two
    such rows that do *not* share an identical `created_at`, ordering by
    `(created_at, sequence)` is unaffected — `created_at` alone already
    orders them correctly regardless of what backfill value `sequence`
    landed on. For two such rows that *do* share an identical `created_at`,
    their relative order was **already unknowable** before this migration
    existed — the prior tie-breaker was `id`, a random UUID with zero
    correlation to insertion order, which is the exact defect this column
    was built to close. The backfill does not regress that: it replaces
    one arbitrary-for-ties ordering (`id`) with another
    (heap-scan-order-derived `sequence`), not a known-correct ordering with
    an unknown one. **No corrective follow-up migration is warranted**: a
    migration recomputing legacy `sequence` values via, say,
    `ROW_NUMBER() OVER (ORDER BY created_at, id)` would only re-derive
    ordering from the same random `id` this system already knows carries
    no chronological information — manufacturing an appearance of recovered
    chronology that does not actually exist, at the real cost of a
    table-wide `UPDATE` (lock/write-amplification) for zero correctness
    gain. Documented honestly instead: **new rows carry a true DB
    insertion sequence; legacy rows that happen to share an identical
    `created_at` have a stable, deterministic ordering after this
    migration, but their original relative insertion order cannot be, and
    never could be, recovered.**
- **Concurrent insert (real threads, real PostgreSQL)**: no duplicate
  sequence, no lost/skipped assignment
  (`conversations/tests/test_concurrency.py`).
- **Ordering semantics**: `(created_at, sequence)` ordering is the correct
  key for "genuinely newest" under a real `created_at` tie — proven both
  under real concurrent insertion (duplicate-free, complete, tie-groups
  correctly sub-ordered) and under a deterministically forced tie
  (`agents/tests/test_context.py`). **A real, previously-uncaught defect**
  was found and fixed applying this same audit to
  `channel_ingress.webchat.list_chat_messages`'s `after`-cursor: it
  compared the cursor anchor's `id` (a random UUID) against
  `message_list_for_conversation`'s actual `(created_at, sequence)`
  ordering — a genuine mismatch that could skip or duplicate a message
  across polls on a real `created_at` tie. Fixed to compare `sequence`,
  matching the queryset's real ordering; regression test forces the exact
  tie and was confirmed to fail against the old `id`-based comparison
  before the fix.

## Residual risks

- **Retry configuration is not uniform across tasks**, as described above.
  Standardizing it was deliberately not done this phase without a decision
  on what each task's correct transient-failure classification actually is
  (unlike `knowledge`'s already-narrow `RetryableIngestionError` split).
- Celery Beat scheduling/packaging for the periodic sweepers
  (`expire_stale_approvals_task`, `recover_stuck_inbound_events_task`,
  the `notifications` due-delivery/expired-claim sweeps, and — new this
  checkpoint — `agents.recovery.recover_stuck_agent_runs` /
  `evaluations.recovery.recover_stuck_evaluation_runs`) is a Phase 17
  deployment-packaging concern, out of scope here. The recovery *logic*
  itself is Phase 16's responsibility and is now closed for every domain
  with a real `RUNNING`-and-abandonable state; only the production
  scheduler/process that invokes these functions periodically remains for
  Phase 17.
- Single-node Docker Compose PostgreSQL/Redis topology (development/demo
  scale) has not been load-tested at internet scale; this phase's
  concurrency proofs establish *correctness* under real concurrent access,
  not throughput ceilings.
- **The stuck-run staleness threshold approximates "worker is dead" via
  `updated_at` in the absence of a real per-run heartbeat/lease — and
  `updated_at` is not refreshed by a run's own intermediate steps**
  (Checkpoint 2A correction: an earlier version of this document asserted
  the defaults were "deliberately far above any realistic single-run
  duration" without deriving that claim; that framing was too confident).
  What is actually true: `AgentRun.updated_at` is set once at claim time
  and not touched again until the run reaches a terminal state or pauses
  for approval — a run legitimately still executing for a long time looks
  exactly as stale as a genuinely dead one, purely by construction. The
  real worst-case duration a *healthy* run can ever legitimately take is
  bounded by `AgentVersion`'s own serializer ceilings
  (`wall_time_limit_seconds<=600`, `provider_timeout_seconds<=300` —
  `agents/serializers.py`), since `check_budget` only re-checks the
  wall-time ceiling *before* starting another provider call
  (`agents/runtime/budgets.py`) — the call already in flight when that
  ceiling trips can still run to its own timeout: ~900s worst case for the
  model-call loop alone. `AGENTS_STUCK_RUN_STALE_SECONDS` /
  `EVALUATIONS_STUCK_RUN_STALE_SECONDS` now default to 3600s and are
  validated at process startup (`config/settings.py`) to never be
  configured below a hard-coded 1800s safety floor derived from that
  arithmetic — raising either threshold is always safe; lowering it below
  the floor is refused outright. This is a real, checked invariant now,
  not an assumption. It remains coarse — a genuinely dead row can sit for
  up to the full threshold before being recovered — and a real heartbeat
  would allow a materially tighter bound without touching the ceiling
  math above; not implemented this checkpoint as a "smallest reliable
  primitive" scope decision.
- **A recovered row's fencing prevents database regression, not an
  already-issued external side effect** — see "External side-effect
  window" above. This is a real, currently-unaddressed reconciliation gap
  (shared with any lost-response scenario, not unique to recovery),
  deliberately out of this checkpoint's scope.
- **`calendar.create_booking` has no reconciliation primitive** (Phase 16
  Checkpoint 4, Part A): the ambiguous-outcome fix stops the backend's own
  retry/redelivery machinery from automatically duplicating a booking, but
  a manually-issued *new* request after an ambiguous failure — a fresh
  idempotency key, believing the first attempt failed — can still create a
  real duplicate event. The Google adapter has no `list`/`search` method to
  look up a possibly-already-created event by its stored
  `extendedProperties` key; building one is a genuine feature addition,
  deliberately out of scope. See "Calendar ambiguous-outcome fix" above.
- **`AgentRun`'s recovery safety bound is narrower than "automatically
  safe forever"** (Phase 16 Checkpoint 3, Part A section 8): the 900s
  worst-case derivation above holds only for the *currently registered*
  execution surface — `AgentVersion.wall_time_limit_seconds<=600` /
  `provider_timeout_seconds<=300` (both DRF serializer ceilings) plus one
  trailing tool call's own timeout. That trailing timeout is
  **code-owned, not centrally capped**: every `ToolDefinition.max_timeout_seconds`
  in the codebase today is a `ToolSpec` constant seeded by
  `tools.services.sync_tool_catalog` from code (`tools/demo_tools.py`,
  10s max observed) — `ToolDefinitionSerializer` is entirely
  `read_only_fields = fields`, so there is no API path for an operator to
  register a tool with a larger timeout at runtime. The invariant that
  actually holds is: *current registered/configurable execution bounds (≤900s)
  < recovery threshold floor (1800s)* — not an automatic guarantee that
  survives a future code change. If a future tool is added with a
  materially larger `max_timeout_seconds` (or the serializer ceilings on
  `AgentVersion` are raised), this arithmetic must be re-derived and the
  settings-time floor (`_AGENT_RUN_STUCK_RECOVERY_SAFE_FLOOR_SECONDS` in
  `config/settings.py`) re-checked by hand — no runtime validation links
  a per-tool DB timeout to the global staleness threshold, deliberately:
  `ToolDefinition` rows are dynamic, per-workspace-agnostic catalog data,
  not startup-time `env()` config, so no `settings.py`-time check could
  observe them, and a DB-level `CHECK` comparing a table column against a
  Django setting value isn't expressible as a portable constraint. Given
  every current tool sits comfortably under the floor and the catalog is
  code-only (not admin-configurable), building new cross-cutting
  validation machinery for a currently-hypothetical future risk was judged
  overengineering for this checkpoint; this paragraph is the explicit,
  narrow documentation of the invariant instead.

## Lock-order audit (Phase 16 Checkpoint 2 Part D)

Every `select_for_update()` call site in `agents`, `approvals`, `tools`,
`evaluations`, `notifications`, and `channel_ingress` was inventoried for
multi-model lock sequences (the only shape that can deadlock via lock-order
inversion). Only one genuine cross-model chain exists in each direction
with no reverse counterpart found anywhere:

- `evaluations`: Run → Result, everywhere (`_claim_evaluation_result`,
  `cancel_evaluation_run`, `_record_case_completion`,
  `finalize_evaluation_run`, and this checkpoint's own
  `recover_stuck_evaluation_runs`) — the one place an inversion was ever
  found (Checkpoint 1, Result → Run in `_claim_evaluation_result`, fixed).
  Re-verified deadlock-free this checkpoint: 11 stress runs of
  `evaluations/tests/test_concurrency.py` (33 executions total), 0
  deadlocks.
- `agents.cancel_agent_run` locks `AgentRun` → `ApprovalRequest`
  (via `approvals.services.cancel_approval_for_execution`) → `ToolExecution`
  (a plain conditional `.update()`, not a second `select_for_update()`).
- `approvals.decide_approval` / `expire_stale_approvals` lock
  `ApprovalRequest` → `ToolExecution` (via `_terminate_execution`, also a
  plain conditional `.update()`, never `select_for_update()`).
- `tools.execution`'s policy gate creates the `ApprovalRequest` row (a
  plain `INSERT`, not a lock on an existing row — no concurrent caller can
  reference an approval id that has not committed yet) before locking
  `ToolExecution` — never the reverse of an existing lock.

No path locks `ApprovalRequest` before `AgentRun`, and no path in
`tools/execution.py` ever queries `ApprovalRequest` at all — so neither
one-directional chain above has a reverse counterpart anywhere in the
codebase. `notifications`/`channel_ingress`/`tools` lock exactly one model
type per transaction in every other call site. Conclusion: **zero new lock
inversions found**; the evaluations fix from Checkpoint 1 remains the only
real one.

## Query performance (Phase 16 Checkpoint 2 Part E/F/G)

Measured with `CaptureQueriesContext` against real PostgreSQL at 1/10/50
rows (or the resource's own natural cap, e.g. integrations at 4 — Postgres
enforces one connection per `(workspace, provider)`): customer list,
conversation list, conversation message history, ticket list, agent list,
agent run list, integration list, evaluation dataset list, evaluation
run/result list, channel endpoint list were all **CONSTANT** — identical
query count regardless of row count. `approvals`' list view was verified by
code inspection (`select_related("decision")`, no nested/method serializer
field) rather than a full load, for the same conclusion. No N+1 defect was
found in any measured list endpoint; nothing here needed
`select_related`/`prefetch_related` changes.

Two real, unmeasured-by-query-count issues were found and fixed instead:

1. **`agents.context.build_conversation_context`** loaded *every* eligible
   message in a conversation into Python before trimming to
   `max_messages` — a single query, so query-count profiling alone would
   never have surfaced it, but genuinely unbounded row-fetch/memory for a
   long-lived conversation. Fixed to push the same role-eligibility rule
   `_normalized_role` already encoded into a DB `Q()` filter, then fetch
   only `ORDER BY -created_at, -sequence LIMIT max_messages` — the true
   total (for the `truncated` flag) still comes from a separate, cheap,
   indexed `.count()`. Regression test asserts the fetch query's SQL
   literally carries `LIMIT <max_messages>` regardless of conversation
   length (`agents/tests/test_context.py::TestConversationContextQueryBounds`).
2. **`agents.recovery`/`evaluations.recovery`'s own sweep queries**
   (`status=RUNNING, updated_at<=cutoff`, deliberately global/cross-
   workspace) had no supporting index — `EXPLAIN ANALYZE` against 308k
   synthetic `AgentRun` rows showed a full parallel sequential scan (~27ms,
   ~11,900 buffer reads); against 150k synthetic `EvaluationRun` rows,
   ~18ms and ~6,400 buffer reads. A new `(status, updated_at)` index on
   each model brought both to an index scan (~0.2ms / ~0.13ms, ~100 buffer
   reads) — migrations `agents/0007` and `evaluations/0004`, additive only.

`channels/webchat` message history and `evaluations` run/result pagination
were already DB-`LIMIT`-bounded (`CHANNEL_WEBCHAT_MESSAGE_HISTORY_LIMIT`,
DRF's standard paginator) — verified by inspection and the constant query
counts above, not re-derived here.

## Phase 16 / Phase 17 boundary (reconfirmed, Checkpoint 4)

**Phase 16 owns and has closed**: recovery semantics for every domain with
a real `RUNNING`-and-abandonable state (`agents`, `evaluations`); the
false-positive evaluation-recovery fix; the calendar ambiguous-outcome
retry fix; retry/idempotency classification (transient vs. permanent,
provider-native vs. no-provider-dedup) for every registered side-effecting
tool; measured, reproducible query-bound and index-usage proof at
representative scale; production-image build/boot verification; and
worker-restart, Redis-outage, and PostgreSQL-outage behavior, all exercised
against the real built image rather than only the test suite.

**Phase 17 owns and remains untouched by this checkpoint**: Celery Beat
process/schedule packaging for every periodic sweep named above (no Beat
schedule was added this checkpoint, on instruction); production reverse
proxy/runtime composition; final backend acceptance packaging and the
Phase 16 release gate itself (deliberately not run this checkpoint).
