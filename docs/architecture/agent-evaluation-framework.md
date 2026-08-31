# Agent Evaluation Framework

Phase 12 adds a first-class evaluation system for deterministically scoring
the agent runtime against curated cases, comparing agent versions, and
gating releases on regression thresholds — without forking the production
orchestration, policy, or tool-execution boundaries it evaluates.

## Data model

```
EvaluationDataset ──< EvaluationCase
                         │ (snapshotted at run creation)
                         ▼
EvaluationRun ──< EvaluationCaseSnapshot ──< EvaluationResult ──> AgentRun
```

- **EvaluationDataset / EvaluationCase** — mutable, workspace-scoped content.
  A case carries `input_message`, a typed `seeded_context` (deterministic
  business fixtures and, for the default provider mode, a scripted LLM
  scenario sequence), and typed `expectations` (allowed/forbidden tools,
  required or acceptable tool sequences, expected approval behavior,
  structured outcome assertions, reference answer). Both JSON fields are
  validated against Pydantic schemas (`evaluations/schemas.py`) before
  save — never arbitrary executable content.
- **EvaluationRun** — one execution of a dataset against one published
  `AgentVersion`. An explicit lifecycle (`pending → running →
  {succeeded, partial, failed, cancelled}`) mirrors `AgentRun`'s own
  state-machine conventions (`select_for_update` + an explicit allowed-
  transitions table).
- **EvaluationCaseSnapshot** — an immutable copy of a case's content taken
  the moment its run is created. **Reproducibility strategy**: datasets and
  cases stay simple and freely editable; a run only ever reads its own
  snapshots, so editing a case on Tuesday never changes what a run created
  on Monday meant. This was chosen over versioned dataset publishing as the
  smaller, sufficient mechanism for the guarantee actually required.
- **EvaluationResult** — one case execution's outcome: status, a reference
  to the real `AgentRun` that was executed, structured `scorer_output`,
  `passed`, a bounded `failure_code`, latency/token/cost fields, and
  `replay_of` for replay lineage. A partial unique constraint
  (`case_snapshot` where `replay_of IS NULL`) makes "one initial result per
  snapshot" a database invariant while still allowing an unlimited number of
  replays against the same snapshot.

## Execution path — the same production orchestration

An evaluation case is executed through the identical seam production runs
use: `agents.services.claim_agent_run` + `execute_claimed_agent_run`. The
only substitution is the LLM provider instance — `execute_claimed_agent_run`
now accepts an optional `provider` override, used to inject a per-case
`DeterministicFakeLLMProvider` built from the case's scripted scenario
sequence (`evaluations/providers.py`). Tool execution, policy evaluation,
approval gating, and audit all run unmodified. A new `AgentRunTrigger.EVALUATION`
value distinguishes evaluation-triggered runs in traces and metrics without
otherwise changing their handling.

Provider isolation is fail-closed: `execute_evaluation_case` refuses to run
at all while `INTEGRATIONS_LIVE_PROVIDERS_ENABLED` is true, rather than risk
a real refund, booking, or notification firing from a scripted case.

## Deterministic scoring

`evaluations/scoring.py` computes an `EvaluationScorerOutput` purely from
already-persisted artifacts of the `AgentRun` it scores: its `ToolExecution`
rows, any `ApprovalRequest` gating them, and the run's own terminal state
and usage counters. No LLM-as-judge, no chain-of-thought — a metric the
runtime cannot actually prove (for example, intent classification, which
nothing in the runtime currently persists) is left `null`/`not evaluated`
rather than guessed.

Safety-critical outcomes are reported as their own explicit
`EvaluationFailureCode` rather than folded into a generic low score: a
forbidden tool that *actually executes* (as opposed to one the policy gate
correctly blocked or terminated for approval) is `forbidden_tool_violation`;
an approval-required action that proceeds without one is
`approval_violation`.

Raw metric values (`EvaluationResult.scorer_output`), the case pass/fail
decision (`EvaluationResult.passed`), and run/dataset aggregates
(`EvaluationRun.passed_cases`/`failed_cases`) are kept as three distinct
layers — there is no combined weighted score.

## Batch execution, idempotency, and concurrency

A run's snapshots and `PENDING` `EvaluationResult` rows are created together,
in the same transaction as the run, and dispatched via
`transaction.on_commit`. Each case then runs as its own Celery task
(`execute_evaluation_case_task`), which claims its `EvaluationResult` under
`select_for_update` before doing anything — a redelivered task for an
already-claimed result simply returns the existing terminal row unchanged.
The parent run's aggregate counters and finalization are likewise computed
under a row lock, so two workers racing to finish the run's last two cases
converge on exactly one finalization.

Partial failure is a first-class run outcome: a case that fails for
execution reasons (an invalid scenario, a provider or scoring exception) is
recorded as `EvaluationResultStatus.FAILED` and does not abort the batch.
The run finalizes to `PARTIAL` if some but not all cases failed this way,
`FAILED` if every case did, and `SUCCEEDED` otherwise — independent of how
many cases *scored* as failing an assertion, which is a normal (not
infrastructural) outcome.

## Replay

Replay creates a brand-new `EvaluationResult` (`replay_of` pointing at the
original) against the same immutable snapshot, and re-executes it through
the identical pipeline. The original result is never mutated, and a replay
never contributes to its parent run's aggregate counters.

## A/B comparison and regression thresholds

`compare_evaluation_runs` pairs two runs by case key and rejects the
comparison outright (rather than silently comparing a subset) if their case
sets differ. It returns per-metric baseline/candidate values and deltas
(pass rate, forbidden-tool violations, approval violations, handoff rate),
then evaluates the candidate run's own `threshold_config` snapshot against
them — `min_pass_rate`, `max_pass_rate_drop`, `zero_forbidden_tool_violations`,
`zero_approval_violations`, `max_handoff_rate_increase`. Every threshold is
explicit and persisted on the run that used it; there is no implicit
weighting.

## Privacy and observability

Metrics (`supportpilot_evaluation_runs_total`,
`supportpilot_evaluation_cases_total`,
`supportpilot_evaluation_case_duration_seconds`,
`supportpilot_evaluation_regressions_total`) carry only bounded, code-owned
label values — never a dataset/case/run/agent-version id, raw intent, or
case content. Spans (`evaluation.case`) carry only ids and outcome enums.
`EvaluationResult`/`EvaluationCaseSnapshot` never store hidden reasoning —
only the same safe, structured facts the rest of the runtime persists.

## Provider isolation and CI

Default (and CI) evaluation runs exclusively against
`DeterministicFakeLLMProvider` and the existing fake business-integration
providers (already the default whenever `INTEGRATIONS_LIVE_PROVIDERS_ENABLED`
is unset). No evaluation path requires OpenAI, Stripe, or any other paid
credential. A real-model evaluation mode is architecturally possible as a
future, explicit opt-in — it is not implemented, and nothing in this phase
makes CI depend on it.
