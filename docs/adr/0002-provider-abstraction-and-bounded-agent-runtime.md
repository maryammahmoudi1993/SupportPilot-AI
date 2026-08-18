# ADR 0002: Provider Abstraction and Explicit Bounded Agent Runtime

- Status: Accepted
- Date: 2026-08-18

## Context

Phase 5 introduces the first code that calls a large language model. The
platform must not become coupled to one vendor's SDK, must never let a model
run unbounded, and must never persist hidden model reasoning. It also must
stay entirely offline for CI and local development by default, since paid
provider credentials are not part of the normal development loop.

## Decision

1. **Typed provider protocol.** All runtime and service code depends on
   `agents.providers.protocol.LLMProvider`, a structural `Protocol` over
   typed `LLMRequest`/`LLMResponse` dataclasses
   (`agents.providers.schemas`). No vendor SDK type crosses this boundary.
2. **Deterministic fake by default.** `AGENTS_LLM_PROVIDER` defaults to
   `"fake"`, backed by `DeterministicFakeLLMProvider`, a scenario-driven,
   offline implementation (`agents.providers.fake`). The real OpenAI adapter
   (`agents.providers.openai_adapter.OpenAIProvider`) is constructed only
   when `AGENTS_LLM_PROVIDER=openai` and `AGENTS_OPENAI_API_KEY` is set; a
   misconfigured real provider fails with a stable
   `ProviderConfigurationError` rather than booting silently or falling back
   to the network in a test environment.
3. **Normalized error taxonomy.** Every adapter raises a subclass of
   `agents.providers.errors.ProviderError` with a stable `code`, a safe
   `safe_message`, and an explicit `retryable` flag. No adapter lets a raw
   SDK exception, HTTP header, or credential escape.
4. **Explicit, bounded runtime.** `agents.runtime.graph` builds a small
   LangGraph `StateGraph`: `prepare_run -> check_budget -> generate_response
   -> validate_provider_result -> finalize_response`, with a single bounded
   retry edge back to `check_budget` gated by a strictly increasing attempt
   counter and the run's own `max_model_calls`/`max_retry_attempts` budget.
   There is no unconditional loop; the graph always terminates.
5. **Budgets checked before spending.** `agents.runtime.budgets.check_budget`
   evaluates model-call count, step count, wall-clock elapsed time, token
   total, and (only when the provider actually reported a cost) estimated
   cost — before another provider call is scheduled, not after.
6. **Service-owned state transitions.** `agents.services` is the only code
   that writes `AgentRun.status`. Every transition re-reads the row under
   `select_for_update()` inside a transaction and validates the *current*
   database state, which is what makes duplicate claims
   (`claim_agent_run`), racing cancellations, and terminal-state reopening
   safe without relying on request-level locking.
7. **No hidden reasoning.** `AgentStep` records only safe, structured facts:
   step type, provider/model, token counts, latency, and safe error codes.
   The graph state itself never carries private chain-of-thought — only the
   final `final_response` text and normalized provider metadata.

## Consequences

Benefits:

- swapping or adding a provider (Anthropic, a self-hosted model) requires a
  new adapter only, not runtime changes;
- every runtime test is deterministic and offline by default;
- budget exhaustion, provider failure, and cancellation are structurally
  distinguishable states (`budget_exceeded` vs `failed` vs `cancelled`), not
  overloaded error codes;
- audit and safe trace data are sufficient to reconstruct *what happened*
  operationally without ever exposing hidden reasoning.

Trade-offs:

- the graph is intentionally minimal (single provider call plus one bounded
  retry) — a genuinely multi-step tool-using agent is out of scope for this
  phase and will be built in Phase 6 on top of this same provider/runtime
  boundary;
- cost enforcement is only as good as the metadata a provider actually
  reports; the fake provider defaults to no cost, so cost-budget tests use
  an explicit scenario with `estimated_cost_usd` set.
