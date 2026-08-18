# AI Provider Layer and Agent Runtime Foundation

Phase 5 adds the first code that calls a large language model. It ends at a
single, bounded, observable execution of one agent version against one
input; it does not implement tool execution, policy evaluation, human
approval, or a multi-tool autonomous loop — those are later phases.

## Provider boundary

```text
agents.services / agents.runtime.graph
        |
        v
agents.providers.protocol.LLMProvider   (typed contract)
        |
        +--> agents.providers.fake.DeterministicFakeLLMProvider   (default)
        |
        +--> agents.providers.openai_adapter.OpenAIProvider       (opt-in)
```

`LLMRequest`/`LLMResponse`/`LLMUsage` (`agents.providers.schemas`) are the
only types that cross the boundary — no vendor SDK object, and no field sized
for hidden reasoning. `AGENTS_LLM_PROVIDER` (default `"fake"`) selects the
adapter; `AGENTS_OPENAI_API_KEY`/`AGENTS_OPENAI_BASE_URL` configure the real
one. A misconfigured real provider raises `ProviderConfigurationError`
instead of booting broken or silently reaching the network.

Every adapter failure is normalized to a subclass of
`agents.providers.errors.ProviderError` with a stable `code`, a safe
`safe_message`, and an explicit `retryable` flag:

| Code | Retryable |
| --- | --- |
| `provider_authentication_failed` | no |
| `provider_rate_limited` | yes |
| `provider_timeout` | yes |
| `provider_temporarily_unavailable` | yes |
| `provider_invalid_request` | no |
| `provider_malformed_response` | no |
| `provider_content_rejected` | no |
| `provider_configuration_error` | no |
| `provider_unknown_error` | no |

See ADR 0002 for the full rationale.

## Domain model

```text
Workspace
  `-- AgentDefinition (status: active | inactive | archived)
        `-- AgentVersion (status: draft | published | retired)
              `-- AgentRun (status: pending | running | succeeded | failed
                                     | cancelled | budget_exceeded)
                    `-- AgentStep (safe, enumerated trace events)
```

An `AgentVersion` carries its own model configuration (`provider`, `model`,
`temperature`, `max_output_tokens`, `system_prompt`) and its own execution
budgets (`max_model_calls`, `max_steps`, `wall_time_limit_seconds`,
`provider_timeout_seconds`, `max_total_tokens`, `max_estimated_cost_usd`,
`max_retry_attempts`). A version is immutable once published: a new
configuration always means a new, sequentially-numbered version
(`agent_ver_definition_version_uniq`), so a run's recorded configuration can
never silently drift out from under it. Only a `draft` version can be
published; publishing is a one-way transition.

`AgentRun` references exactly one `AgentVersion` (`on_delete=PROTECT`, so a
version cannot be deleted while runs reference it) and optionally a
`conversations.Conversation` / `tickets.Ticket` for provenance. Runs can only
be created against a `published` version.

## Run lifecycle

```text
pending -> running -> succeeded
                    -> failed
                    -> cancelled
                    -> budget_exceeded
pending -> cancelled
```

All four right-hand states are terminal; no transition ever leaves a terminal
state. `agents.services` owns every write to `AgentRun.status`. Each
transition re-reads the row with `select_for_update()` inside a transaction
and checks the *current* database status before writing — not the status the
caller believes it holds — which is what makes the following safe without
extra locking:

- **Idempotent claim.** `claim_agent_run` only moves `pending -> running`; a
  second concurrent/duplicate claim attempt for the same run sees a
  non-`pending` status under the row lock and returns `None` instead of
  re-executing.
- **Racing cancellation vs. completion.** `cancel_agent_run` and
  `_complete_run`/`_fail_run`/`_budget_exceeded_run` all check the row's
  current status before writing; whichever transaction commits first wins,
  and the loser's guard clause makes it a safe no-op rather than a corrupted
  state.
- **Terminal-state protection.** Every completion/failure/cancellation
  helper returns the row unchanged if it is already in
  `AGENT_RUN_TERMINAL_STATUSES`.

## Bounded runtime (LangGraph)

```text
START -> prepare_run -> check_budget --exceeded--> END
                              |
                          proceed
                              v
                     generate_response --end (non-retryable / exhausted)--> END
                              |
                          continue
                              v
                  validate_provider_result --error--> END
                              |
                             ok
                              v
                     finalize_response -> END
```

A single conditional edge from `generate_response` back to `check_budget`
implements a *bounded* retry: it is only taken while the provider error is
marked `retryable`, `attempt < max_retry_attempts`, and
`model_call_count < max_model_calls` — both counters are strictly increasing
every time the edge is taken, so the graph always terminates. Budget checks
(`agents.runtime.budgets.check_budget`) run before every attempt to call the
provider, never after, and evaluate model-call count, step count, elapsed
wall time, token total, and — only when the provider actually reported a
cost — estimated cost against the version's configured ceilings.

Each node records one safe `AgentStep` through a closure
(`agents.services._record_step_factory`) rather than writing to the database
itself; persistence stays in the service layer, keeping the graph focused on
orchestration.

## Async execution and idempotency

`create_agent_run` creates the row as `pending` and uses
`transaction.on_commit` to enqueue `agents.tasks.execute_agent_run_task`,
avoiding the classic race where a worker picks up a task before the creating
transaction has committed. The Celery task calls
`agents.services.execute_agent_run` — never runtime logic directly — which
begins with `claim_agent_run` and is therefore safe to invoke more than once
for the same `run_id` (Celery redelivery, an operator retry, or a second
worker). The task's own retry budget (`max_retries=3`) only matters for
truly unexpected failures — every provider/runtime failure the graph can
anticipate is already caught and turned into a terminal run state without
raising out of `execute_agent_run`.

## Tenant isolation and RBAC

Every selector in `agents.selectors` filters by `workspace` before resolving
an object and raises `Http404` on a miss, so a valid UUID from another
workspace behaves identically to a UUID that does not exist. `AgentStep` also
carries a denormalized `workspace` for the same direct-filter pattern used by
`knowledge.KnowledgeChunk`.

`agents.permissions` defines two capability sets, mapped to the same
database-backed `WorkspaceMembership.role` used everywhere else in the
platform (never a JWT/header/client claim):

| Capability | Roles |
| --- | --- |
| Configure agents (definitions, versions, publish) | owner, admin, support_manager |
| Run/cancel agents | owner, admin, support_manager, support_agent |
| View agents/runs/steps | any active workspace member |

## Safe trace and audit

`AgentStep.step_type` is a fixed enum of operational events (`run_started`,
`budget_checked`, `provider_call_started/succeeded/failed`,
`response_finalized`, `run_cancelled`, ...). Every field is safe to persist
and to return from the API — see ADR 0003 for why there is structurally no
field for hidden reasoning. `agents.selectors.agent_step_list_for_run` caps
the trace at 200 rows so a run's history can never be returned unbounded.

Administrative/security-relevant state changes are additionally recorded
through the existing `audit` app: `agent.definition_created/updated`,
`agent.version_created/published`, `agent.run_started/cancelled/failed/completed`.

## Input bounds

`AgentRun.input_message` is capped at `MAX_INPUT_MESSAGE_CHARS` (8,000
characters) at the serializer layer; `input_metadata`/`runtime_config`
payloads are size-checked (≤ 8 KB serialized) before being accepted.
