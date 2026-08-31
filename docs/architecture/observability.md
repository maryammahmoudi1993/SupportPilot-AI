# Production observability, metrics, and SLOs

Phase 11 makes the workflows the platform already runs — HTTP requests,
agent orchestration, tool execution, policy/approval decisions, human
handoff, and durable notification/webhook delivery — operationally
observable, without becoming part of business correctness itself. This
document describes what is actually implemented (updated as later Phase 11
blocks land), not an aspirational target.

## Non-goals

This phase does not add Kafka, ClickHouse, Elasticsearch, Grafana, a
Prometheus *server*, Tempo, Jaeger, Loki, Sentry, a customer-facing
analytics dashboard, a generic event bus, or a metrics/log/trace storage
backend of its own. PostgreSQL remains the business/reliability source of
truth (`Delivery`, `AgentRun`, `ApprovalRequest`, ...); telemetry is derived
operational information layered on top of it, never stored back into it.

## Design principles

1. Telemetry never determines business state — a metrics/export failure
   never blocks, retries, or alters a business operation (see
   [Failure isolation](#failure-isolation)).
2. Metrics are low-cardinality by construction — every label is drawn from a
   small, bounded, server-owned set (see [Cardinality rules](#cardinality-rules)).
3. Logs may contain operational identifiers (a `delivery_id`, an
   `agent_run_id`); metric labels never may.
4. The metrics endpoint is deployment infrastructure, protected by a single
   server-owned bearer token — never workspace RBAC, never a tenant-facing
   API.

## Metrics architecture

**Library**: [`prometheus_client`](https://github.com/prometheus/client_python)
— a pure exposition-format client library, not a server or SDK/agent. It was
chosen over introducing OpenTelemetry because Phase 11's tracing/correlation
needs (see [ADR 0009](../adr/0009-vendor-neutral-observability-with-bounded-cardinality-telemetry.md))
are met by structured logging and existing model relationships, without a
second, heavier instrumentation stack; it was chosen over hand-rolling a
metrics format because Prometheus exposition text is a de facto standard any
compatible scraper (Prometheus itself, Grafana Agent, a vendor's OTLP/Prom
bridge) already understands.

**Registry**: every metric is declared exactly once, in
`observability/metrics.py` — never ad hoc inside a view, service, or task —
so names, label sets, and cardinality can be reviewed in one place. All
metric names share the `supportpilot_` prefix.

### HTTP metrics (Block 1)

| Metric | Type | Labels |
|---|---|---|
| `supportpilot_http_requests_total` | Counter | `method`, `route`, `status_class` |
| `supportpilot_http_request_duration_seconds` | Histogram | `method`, `route` |

`route` is the resolved Django URL name (`request.resolver_match.view_name`)
— never the raw request path. A request that never resolves to a view (a
genuine 404, or an attacker probing many distinct paths) collapses to the
single bounded value `"unmatched"` rather than creating one time series per
attempted path — this is a cardinality-attack defense, not just a naming
convenience (see [Cardinality rules](#cardinality-rules)). `status_class` is
one of `2xx`/`3xx`/`4xx`/`5xx`, with `other` as a stable fallback for an
out-of-range status produced by application code. `method` is one of
`GET`/`POST`/`PUT`/`PATCH`/`DELETE`/`HEAD`/`OPTIONS`; custom or unknown verbs
collapse to `OTHER` before reaching the metrics registry.

`observability/middleware.MetricsMiddleware` records both metrics for every
completed request, after `common.middleware.StructuredLoggingMiddleware` in
`MIDDLEWARE` — a recording failure is caught and logged, never allowed to
fail the actual HTTP response (see [Failure isolation](#failure-isolation)).
The metrics endpoint itself (`route == "metrics"`) is excluded from these
metrics so scraping it does not create an ever-growing self-referential
entry in its own output. `/health/`/`/ready/` (`route ==
"health:health"`/`"health:readiness"`) are excluded too (Phase 11 Block 5):
high-frequency, always-200, near-zero-latency probe traffic is not eligible
traffic for the API availability/latency SLOs
(`docs/observability/slos.md`) — left included, probe volume would dilute a
real 5xx spike's visible ratio and skew p95 latency optimistic. They remain
traced (see [Tracing](#tracing) below) — only the request-count/duration
*metrics* exclude them.

Later blocks add agent/tool/policy/approval/handoff/delivery/webhook
metrics; this table will grow with them.

## Cardinality rules

A metric label populated from an unbounded value — a workspace, customer,
delivery, request, or webhook-endpoint id; a raw URL; an exception message;
a provider response body — turns one time series into an unbounded number of
them, which is a real production outage vector for any metrics backend, not
a style nitpick.

**Forbidden as metric labels** (anywhere in this codebase):
`workspace_id`, `user_id`, `customer_id`, `conversation_id`, `ticket_id`,
`agent_run_id`, `tool_execution_id`, `delivery_id`, `webhook_event_id`,
`webhook_endpoint_id`, `request_id`, `trace_id`, a raw URL, an email
address, raw exception text, a provider response body.

**Allowed bounded labels**: HTTP method, the resolved route name (or
`"unmatched"`), HTTP status class, an agent's bounded terminal outcome, a
tool name (from the server-owned tool registry), a provider type (from the
server-owned provider registry), an approval/handoff outcome, a delivery
channel/outcome, a webhook response class, a safe server-owned error code,
and a Celery task name (from the bounded application task registry).

These identifiers remain fully available where they belong: in structured
logs, and in the existing model relationships a request/delivery/agent-run
id already lets an operator query (see
[Trace/log correlation](#tracelog-correlation)).

## Multiprocess correctness

Production runs multiple Gunicorn worker processes (`--workers 3`) and
separate Celery worker processes. `prometheus_client` decides, **at metric
construction time** (module import, once per process), whether to use its
multiprocess-safe value class — purely by checking whether
`PROMETHEUS_MULTIPROC_DIR` is present in the environment *before* that
import happens.

`config/gunicorn_conf.py` makes this correct for the Gunicorn process tree
specifically:

- `on_starting` runs once in the master, before any worker forks. It wipes
  and recreates a fixed multiprocess directory and sets
  `PROMETHEUS_MULTIPROC_DIR` — inherited by every forked worker before that
  worker imports `observability.metrics`, which is exactly the ordering
  `prometheus_client` requires. Wiping the directory on every master start
  avoids aggregating stale mmap files left over from a previous
  container/deploy into the current scrape.
- `child_exit` runs whenever a worker exits and calls
  `prometheus_client.multiprocess.mark_process_dead`. The client removes
  live-gauge files for that worker. Counter and histogram files are retained
  deliberately so their cumulative values survive a worker recycle; the next
  master start removes them with the rest of the multiprocess directory.
  Block 1 defines counters and histograms only, but the hook also makes future
  live gauges safe.

Rendering a scrape (`observability.metrics.render_metrics`) branches at
**render time**: if `PROMETHEUS_MULTIPROC_DIR` is set, it builds a fresh
`CollectorRegistry` wired to a `MultiProcessCollector` that reads and
aggregates every process's mmap files from disk; otherwise it reads the
single default in-process registry directly.

Celery workers and `manage.py` commands are deliberately left in
`prometheus_client`'s default single-process mode — no multiprocess
directory needs to exist for them, and none of Phase 11 Block 1's metrics
(HTTP-only) are recorded there. This matches the requirement that ordinary
local/dev/test/management-command runs stay simple: the application starts
and every normal test runs without any Prometheus server, collector, or
multiprocess directory present at all.

## Metrics endpoint

`GET /metrics/` (`observability/views.py`) — deliberately a plain Django
view, not a DRF `APIView`, so it is never introspected into the public
OpenAPI schema and never reachable through DRF's JWT/session authentication
or workspace RBAC. It is deployment infrastructure, not a tenant API.

- Disabled unless `OBSERVABILITY_METRICS_ENABLED` (default `True`).
- Requires `Authorization: Bearer <OBSERVABILITY_METRICS_TOKEN>`, compared
  with `hmac.compare_digest` (constant-time — a naive `==` would let an
  attacker recover the token one byte at a time via response-timing
  measurements).
- Every denial path — disabled, missing header, malformed header, wrong
  token — returns an identical generic `404`, so a denial never leaks
  *which* of those reasons applied.
- A production (`DEBUG=False`) boot with metrics enabled and no token
  configured fails at settings-import time rather than silently exposing an
  endpoint nothing can deny requests from (`config/settings.py`). `DEBUG=True`
  local/dev runs are exempt from that startup check, but the endpoint itself
  still denies every request until a token is actually configured — there is
  no "no auth required in dev" code path.

## Failure isolation

Required invariant: a metrics-recording or export failure must never affect
the business operation it was measuring. `MetricsMiddleware` wraps its
single recording call in a broad `except Exception` that logs a warning and
returns the original response unchanged — proven by
`TestMetricsMiddlewareFailureIsolation` in
`observability/tests/test_middleware.py`, which forces the recorder to raise
and asserts the HTTP response is unaffected. Later blocks extend this same
invariant to agent/tool/delivery instrumentation as those call sites are
added.

## Trace/log correlation

Phase 11 Block 2 was amended to add distributed tracing via the
OpenTelemetry API + SDK (see the "Amendment" section of
[ADR 0009](../adr/0009-vendor-neutral-observability-with-bounded-cardinality-telemetry.md)
for why, and what did/did not change). Correlation across a request, and
across the Celery boundary, now exists through two complementary,
deliberately distinct mechanisms — see "Distributed tracing" below for the
second one:

- `request.request_id` (`common.middleware.RequestIdMiddleware`), present on
  every structured log line the request produces
  (`common.middleware.StructuredLoggingMiddleware`).
- The existing model relationships an operator can already query — an
  `AgentRun`, `ToolExecution`, or `Delivery` id already links back to its
  workspace and, transitively, to the request that produced it.
- **Block 2**: `common.correlation` — a single `contextvars.ContextVar`
  bound once at whichever boundary owns the id (`RequestIdMiddleware` for an
  HTTP request, `common.tasks.CorrelatedTask` for a Celery task) and read
  everywhere else via `get_correlation_id()`. `CorrelationIdLogFilter`
  (wired into `LOGGING["handlers"]["console"]["filters"]`) injects it into
  every structured log record automatically, so no call site threads it
  through `extra=` by hand — the field is simply always present (empty
  string outside any bound scope).

### Celery boundary (Block 2)

Every first-party `@shared_task` is declared with
`base=common.tasks.CorrelatedTask`. A dispatch call site passes
`correlation_id=get_correlation_id()` as an ordinary task keyword argument
(never as message headers, and never mixed into the task's real business
arguments) — falling back to `None` when there is no active scope, e.g. a
Beat-triggered sweep with no originating request. `CorrelatedTask.__call__`:

1. pops `correlation_id` off the incoming kwargs before the task body ever
   sees it (so no existing task signature had to change);
2. binds it for the duration of the task body via `correlation_scope`,
   generating a fresh id first if none was passed, so every task execution
   is always attributable to *some* correlation id;
3. records a bounded Celery task metric (below) with the same
   fail-open guarantee as `MetricsMiddleware` — a broken metrics call never
   affects the task's own result.

This deliberately mirrors `transaction.on_commit`'s existing thin-dispatch
pattern (`_dispatch_run`, `_dispatch_resume`, `_dispatch_ingestion`,
`dispatch_delivery_for_processing`): those functions are the only call
sites that changed, each gaining one `correlation_id=get_correlation_id()`
keyword argument.

### Celery task metrics (Block 2)

| Metric | Type | Labels |
| --- | --- | --- |
| `supportpilot_celery_tasks_total` | Counter | `task_name`, `outcome` (`success`/`failure`/`retry`) |
| `supportpilot_celery_task_duration_seconds` | Histogram | `task_name` |

`task_name` is bounded because it is drawn from this codebase's own
`@shared_task` definitions, never from task input — the same reasoning that
lets the HTTP `route` label use the resolved URL name.

### Distributed tracing (Block 2 remediation, Part B)

`observability/tracing.py` is the sole module that imports `opentelemetry`
(same "one call site" principle as `observability/metrics.py`) — see its
module docstring for the full design. Summary:

- **W3C Trace Context** (`traceparent`/`tracestate`) only, parsed/injected
  exclusively through OpenTelemetry's own propagator — never hand-rolled.
  No baggage propagator is configured (an unbounded, easily-misused-for-
  business-data channel this application has no use for).
- **One server span per HTTP request** (`observability.middleware.TracingMiddleware`,
  placed right after `RequestIdMiddleware`), parented to a valid inbound
  W3C context when present; malformed/absent context safely starts a fresh
  local trace rather than failing the request. `/metrics/` is excluded
  from tracing (recursive scrape noise); `/health/`/`/ready/` are traced —
  readiness does not *depend* on tracing (tracing already fails open), so
  there is no reason to also exclude them.
- **One consumer span per Celery task execution**
  (`common.tasks.CorrelatedTask`, wrapping `observability.tracing.task_span`),
  parented to whatever context `common.tasks._inject_trace_context`
  (connected to Celery's `before_task_publish` signal) placed into the
  message headers at publish time — **never** into business task kwargs,
  keeping `correlation_id`'s existing kwarg-based design (above) completely
  unchanged. A duplicate broker redelivery producing two task executions
  produces two task spans by design; this is a tracing artifact only and
  must never be read as two `DeliveryAttempt`s or two external sends —
  Phase 10's claim/idempotency behavior is what actually prevents that.
- **`trace_id`/`span_id` are surfaced to structured logs**
  (`observability.tracing.TraceContextLogFilter`) alongside
  `correlation_id`/`request_id` — three deliberately distinct fields;
  `request_id`/`correlation_id` is the application's own correlation
  identity, never derived from `trace_id`, and vice versa.
- **OTLP exporter (Block 3).** A `BatchSpanProcessor` + `OTLPSpanExporter`
  (HTTP/protobuf transport) is attached only when
  `OBSERVABILITY_OTLP_ENDPOINT` is configured — absent (the default)
  remains explicit local/no-export mode, not a degraded state.
  `OBSERVABILITY_TRACING_ENABLED` still defaults to `False`: enabling
  tracing and configuring an endpoint are two separate, deliberate
  decisions. Batched and asynchronous by construction — the processor's
  background thread does the actual network I/O, never the request/task
  thread — and constructed lazily inside `get_tracer_provider()`'s
  per-process path, so it is exporter-fork-safe the same way the provider
  itself already is (never built in the Gunicorn master before fork; a
  Celery worker builds its own independently of Gunicorn).
- **Failure isolation** matches metrics' existing guarantee exactly: every
  tracing operation (span start/end, context extract/inject) is wrapped so
  a tracing-internal failure degrades to "no span"/"no context" and never
  affects the HTTP response or Celery task result.
- **No raw exception text is ever recorded onto a span** — span status is
  set from safe, bounded outcome labels only (HTTP status code, Celery
  task outcome), never from `str(exc)`/`repr(exc)`/a provider's response
  text. This is a hard security requirement, not a style choice: span data
  is exactly as exportable/third-party-visible as a metric label, so it
  gets the same "never an unbounded/untrusted value" treatment PII/secrets
  already get everywhere else in this codebase.

**Resolved in Block 3** — see "Celery metrics exposition" below: these
metrics now accumulate correctly in each Celery worker process *and* are
exposed for scraping through one prefork-safe HTTP listener.

## Celery metrics exposition (Block 3)

`config/celery_metrics.py` closes the gap noted above. Architecture (see
the module's own docstring for the full rationale):

```text
Celery worker main process (parent, pre-fork)
    |  worker_init: fresh OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR,
    |  one HTTP listener bound here only
    v
prefork children (inherit the env var via fork)
    |  each writes its own per-PID mmap files under that directory
    v
the one parent-owned HTTP listener
    |  serves render_metrics() (the same multiprocess-aware function
    |  Gunicorn's own /metrics/ route already uses) fresh on every scrape
    v
Prometheus (or any compatible scraper)
```

- **Signals, not Gunicorn's hooks**: `celery.signals.worker_init` fires
  once, in the parent, before the prefork pool forks any child — the
  Celery equivalent of Gunicorn's `on_starting`. `celery.signals.worker_process_shutdown`
  — despite the name — also fires *in the parent*
  (`celery.concurrency.prefork.process_destructor` sends it from the
  pool's own destructor callback with the dead child's `pid`), the same
  timing `child_exit` relies on for Gunicorn; it calls
  `prometheus_client.multiprocess.mark_process_dead`, exactly like
  `config/gunicorn_conf.py::child_exit`.
- **Independent of Gunicorn's own multiprocess directory** (section 5 of
  the Block 3 brief): a separate setting,
  `OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR`, with its own default
  path — Django/Gunicorn and Celery are typically separate deployable
  process groups (often separate containers) and must not be required to
  share a directory or even a filesystem.
- **Security**: no application-level authentication on this listener (it
  is infrastructure telemetry, not a tenant API, the same reasoning
  `/metrics/`'s bearer token exists *because* it is reachable through the
  main Django/DRF process — this listener is a separate, narrower-purpose
  process). Binds to `OBSERVABILITY_CELERY_METRICS_HOST` (default
  `127.0.0.1`, loopback-only) — a non-default bind is an explicit,
  deployment-owned decision that the surrounding network (a private VPC, a
  sidecar-only network namespace, a firewall) is what actually restricts
  access. Off by default (`OBSERVABILITY_CELERY_METRICS_ENABLED=False`).
- **Never a public DRF route**: a raw `http.server.ThreadingHTTPServer` on
  its own port, entirely outside `config/urls.py` — cannot appear in the
  OpenAPI schema by construction, not by an exclusion rule that could be
  forgotten.
- **Proven, not assumed**: `config/tests/test_celery_metrics.py` includes a
  genuine cross-process test — a real Python subprocess sets
  `PROMETHEUS_MULTIPROC_DIR` and records a metric *before ever importing*
  `observability.metrics` (required for the mmap-backed value class to be
  selected), then this test process reads the resulting mmap files back
  via `MultiProcessCollector`, exactly as a real scrape would. A second
  test binds a live listener and scrapes it over a real HTTP connection.
  Stale-directory cleanup on a second "worker master start" and the
  disabled-by-default no-op path are both covered too.

## Domain instrumentation (Block 3)

Extends metrics/tracing from HTTP+Celery infrastructure to the actual
business operations Phase 11 was always meant to cover. Every metric here
follows the same "single call site, bounded labels" discipline as
`observe_http_request`/`observe_celery_task` — see `observability/metrics.py`
for each metric's exact label-set docstring.

### Agent runs

`supportpilot_agent_runs_total{trigger, outcome}` and
`supportpilot_agent_run_duration_seconds{trigger}`, recorded from
`agents/services.py`'s five terminal-transition functions (`_complete_run`,
`_fail_run`, `_budget_exceeded_run`, `_complete_run_as_handoff`,
`cancel_agent_run`) — the same `select_for_update` + status-check guarded,
single-fire boundaries that already make Phase 5's terminal transitions
idempotent, so metric recording inherits that guarantee for free. `trigger`
is `AgentRunTrigger` (manual/conversation/ticket/api); `outcome` is exactly
`AGENT_RUN_TERMINAL_STATUSES` (succeeded/failed/cancelled/budget_exceeded/
handed_off).

- **`WAITING_FOR_APPROVAL` is never observed here** — it is not a terminal
  status (`AGENT_RUN_TERMINAL_STATUSES` excludes it), so no code path ever
  calls `observe_agent_run_terminal` for it.
- **`HANDED_OFF` observes as `outcome="handed_off"`, not `"failed"`** — a
  successful escalation, not a system failure (section 13).
- **Duration is end-to-end** (`created_at` -> the terminal timestamp:
  `completed_at`, or `cancelled_at` for a cancellation), documented as such
  rather than "active compute time" — a run that spent time
  `WAITING_FOR_APPROVAL` includes that human wait, because `AgentRun` has no
  separate compute-only timestamp to derive a narrower measure from
  (section 14).
- **Recorded via `transaction.on_commit`** inside each terminal function's
  own `atomic()` block (section 36-37) — a later rollback can never leave a
  phantom count.
- **One `agent.run` domain span per orchestration attempt**
  (`agents/services.py::execute_claimed_agent_run`), a parent of the
  `llm.generate`/`tool.execute` spans triggered underneath it via ordinary
  span-context nesting. Always ends within the same synchronous call, even
  for a `WAITING_FOR_APPROVAL`/`HANDED_OFF` outcome (section 42-43) — never
  held open across the human-approval wait. Safe attributes only:
  `supportpilot.agent_run_id` (for trace/log correlation — never a
  Prometheus label) and the bounded outcome; never the input message,
  system prompt, or model output.
- **The post-approval resume is a *fresh* `agent.run.resume` span**, not a
  child of the original (already-ended) `agent.run` span (section 42) — a
  forced synchronous parent-child relationship across an arbitrarily long
  human wait would misrepresent the trace. The stable link back to the
  original run is `agent_run_id` itself (present on every step/log/audit
  record for the run already), not span parentage.

### LLM provider calls

`supportpilot_llm_requests_total{provider, outcome}`,
`supportpilot_llm_request_duration_seconds{provider}`, and
`supportpilot_llm_tokens_total{provider, token_type}`, recorded from
`agents/runtime/graph.py`'s `_generate_response` node — the only place
`LLMProvider.generate` is ever called. `provider` is the adapter's own
`name` (fake/openai today; unrecognized values collapse to `other`).
`outcome` is `success` or a `agents.providers.errors.ProviderError`
subclass's own `code` — a small, closed, code-owned taxonomy. **No `model`
label** — `AgentVersion.model` is an operator-settable free-text field, not
a bounded value (section 16-17). Token counts are only observed because
every `LLMProvider.generate` response (including the fake provider's)
already carries real `usage` figures — never estimated or fabricated
(section 17). A `llm.generate` domain span wraps the call, attributed only
with `llm.provider` and the bounded outcome — never the prompt, response,
or a provider's raw exception text (section 18).

### Tool executions

`supportpilot_tool_executions_total{tool_name, outcome}` and
`supportpilot_tool_execution_duration_seconds{tool_name}`, recorded from
the shared, guarded transition functions `tools/execution.py` already had
— `_finalize_success`, `_finalize_failure`, `_transition_blocked_by_policy`
— plus `approvals/services.py::_terminate_execution` for the
`approval_terminated` outcome (a plain queryset `.update()`, guarded by its
own affected-row-count check). These functions are shared by both
`execute_tool` and `resume_after_approval`, so instrumenting them once
covers both paths without risking a missed call site or double-counting an
idempotent replay (`execute_tool`'s `reused=True` short-circuit never
reaches them at all). `outcome` is exactly
`TOOL_EXECUTION_TERMINAL_STATUSES` (succeeded/failed/timed_out/cancelled/
blocked_by_policy/approval_terminated) — the tool's actual status enum, not
an invented taxonomy (section 20). `tool_name` is the tool's registered,
code-owned registry key. A `tool.execute` domain span wraps the handler
invocation in both `execute_tool` and `resume_after_approval`, attributed
with `tool.name`, `supportpilot.tool_execution_id`, and the bounded
outcome — never arguments or the result payload (section 21).

### Policy decisions

`supportpilot_policy_decisions_total{decision}`, recorded from
`tools/execution.py::_run_policy_gate` once its `PolicyEffect` decision has
already committed. `decision` is `allow`/`deny`/`require_approval` — the
actual `PolicyEffect` enum. A fail-closed evaluation-failure observes as
`deny` (the same effect it was actually persisted as on `PolicyEvaluation`)
rather than an invented fourth category. No workspace/policy/tool/user
label (section 22) — none of those are provably bounded across a whole
deployment's policy/tool catalog.

### Approvals

`supportpilot_approval_requests_total` (created, no labels),
`supportpilot_approval_decisions_total{outcome}`, and
`supportpilot_approval_wait_duration_seconds{outcome}`, recorded from
`approvals/services.py`'s `create_or_reuse_approval_request` (created-only
branch), `decide_approval` (approved/rejected), `_expire_if_stale`/
`expire_stale_approvals` (expired), and `cancel_approval_for_execution`
(cancelled) — the real `APPROVAL_TERMINAL_STATUSES` set, and each already
guarded by its own single-fire transition (or, for `decide_approval`, an
idempotent-replay branch that never reaches the metric call at all —
proven by a dedicated no-double-count test). Wait duration is
`created_at -> resolved_at`, never observed for a still-pending request.
Buckets span 10s-24h (`APPROVAL_WAIT_DURATION_SECONDS`), not web-request
latency — a human decision can reasonably take anywhere from seconds to the
request's own TTL. Never in metrics or spans: the approver's private
comment, requester/approver identity, or frozen tool arguments (section
26) — approval ids may appear in structured logs/traces for operational
correlation, never as a metric label.

### Human handoffs

`supportpilot_handoffs_total{reason_code}` (created, from
`tickets/services.py::create_or_reuse_handoff`'s new-row branch) and
`supportpilot_handoff_duration_seconds` (`created_at -> resolved_at`, from
`resolve_handoff` only). `reason_code` is the real, code-owned
`HumanHandoffReason` enum. **Cancellation never observes a duration** — a
cancelled handoff was never actually worked, so a wait/duration figure for
it would be misleading, not merely incomplete (section 27-28); it is
reflected only in audit/webhook records, matching what the repository
actually implements (no fabricated "resolved" instrumentation for a
transition that never happened).

### Known limitations (honestly scoped, not silently dropped)

- No dedicated lightweight span exists for the policy-decision boundary
  itself (only the metric) — the brief marked a policy span "acceptable,"
  not required, and the agent/LLM/tool spans already give section 41's
  trace-lineage test a coherent parent chain to assert against.

A `ToolExecution` cancelled as a side effect of `cancel_agent_run` cascading
into a pending approval (the direct queryset `.update()` to `CANCELLED`
inside `agents/services.py::cancel_agent_run`) was the one Block 3 gap noted
above; it is closed — see `_schedule_cancelled_tool_execution_observations`
in `agents/services.py`, which records `supportpilot_tool_executions_total{outcome="cancelled"}`
via `transaction.on_commit`, guarded by the same conditional-`UPDATE`
row-count single-fire check every other terminal transition here uses.

## Durable delivery / webhook reliability (Block 4)

Extends the same "single call site, bounded labels, commit-safe, fail-open"
discipline to Phase 10's durable delivery layer
(`notifications/services.py`'s `Delivery`/`DeliveryAttempt` state machine and
`webhooks/services.py`'s webhook channel). Every metric here represents an
authoritative, already-committed `Delivery`/`DeliveryAttempt` state
transition — **never** a Celery task execution and **never** a broker
publish, both of which are disposable transport, not ownership (see
`notifications/services.py`'s own module docstring). This is the central
distinction Block 4 exists to get right: a duplicated Celery message, a
redundant sweeper publish, or a broker outage must never be visible as a
duplicated external attempt.

### Metric inventory

| Metric | Type | Labels |
| --- | --- | --- |
| `supportpilot_deliveries_created_total` | Counter | `channel` |
| `supportpilot_delivery_attempts_total` | Counter | `channel` |
| `supportpilot_delivery_attempt_duration_seconds` | Histogram | `channel`, `outcome` |
| `supportpilot_delivery_attempt_failures_total` | Counter | `channel`, `error_category` |
| `supportpilot_delivery_retries_total` | Counter | `channel` |
| `supportpilot_delivery_terminal_total` | Counter | `channel`, `outcome` |
| `supportpilot_delivery_end_to_end_duration_seconds` | Histogram | `channel` |
| `supportpilot_delivery_claim_recoveries_total` | Counter | `channel` |
| `supportpilot_delivery_broker_publication_failures_total` | Counter | `channel`, `source` |
| `supportpilot_delivery_redrives_total` | Counter | `channel` |
| `supportpilot_webhook_responses_total` | Counter | `status_class` |
| `supportpilot_webhook_destination_rejections_total` | Counter | `reason` |
| `supportpilot_delivery_due_count` | Gauge (DB-derived) | `channel` |
| `supportpilot_delivery_expired_claim_count` | Gauge (DB-derived) | `channel` |
| `supportpilot_delivery_oldest_due_age_seconds` | Gauge (DB-derived) | `channel` |

`channel` is `notification`/`webhook` (`DeliveryChannel`); every other label
is one of the small, fixed, server-owned taxonomies documented next to its
`observe_*`/gauge definition in `observability/metrics.py`. As everywhere
else in this registry: no `delivery_id`, `delivery_attempt_id`,
`workspace_id`, `webhook_endpoint_id`, `webhook_event_id`, `request_id`,
`trace_id`, URL, hostname, IP, or raw exception/response text ever becomes a
label.

### Creation, attempts, and the ownership boundary

`observe_delivery_created` fires from `create_delivery`'s own
`transaction.on_commit` — a rolled-back creation, or a reused logical
delivery (an idempotent `notification.send` replay finding an existing
`NotificationDelivery`, or a webhook redrive reusing the same row) never
reaches it, because those callers never call `create_delivery` at all.

`observe_delivery_attempt_claimed` fires once per genuine ownership
acquisition — the exact moment `notifications/services.py::_claim_row`
(shared by `claim_delivery` and `reclaim_expired_delivery`) creates a real
`DeliveryAttempt` row, on commit. A duplicated Celery message, or two
sweepers publishing the same delivery id, never doubles this: only the row
that actually wins the `select_for_update(skip_locked=True)` race reaches
the `on_commit` hook at all — the loser raises `DeliveryNotClaimableError`
before ever getting there.

### Attempt outcome and duration

`observe_delivery_attempt_outcome` is the one call site for a completed
attempt's outcome — `succeeded` (from `complete_delivery_success`),
`retryable_failure`/`terminal_failure` (from `complete_delivery_failure`,
split by whether the delivery could still retry), or `abandoned` (the
reclaim path's own observation for an expired claim's orphaned in-flight
attempt — see below). Duration is the real attempt latency
(`DeliveryAttempt.latency_ms`, or the abandoned attempt's own
claimed-to-reclaimed span) — never PENDING wait, retry backoff, or approval
wait.

A failed outcome additionally increments
`supportpilot_delivery_attempt_failures_total{channel, error_category}`.
`error_category` is a fixed, server-owned 14-value taxonomy
(`_delivery_error_category` in `observability/metrics.py`) that every
`safe_error_code` this codebase produces maps into — `notifications.errors`,
`webhooks.errors`, `webhooks.classification.classify_http_status`'s
per-status codes (collapsed to `remote_4xx`/`remote_5xx`, never the raw
status code as a label), and the reused Phase 7 `integrations.errors.IntegrationError.code`
taxonomy. An unrecognized code — a future error type this table has not
been updated for — collapses to `other`, never a new label value.

### Retries and terminal transitions

`observe_delivery_retry_scheduled` fires only on the committed DB
transition to `RETRY_SCHEDULED` inside `complete_delivery_failure` —
**deliberately distinct** from `supportpilot_celery_tasks_total{outcome="retry"}`.
Phase 10 retry authority is PostgreSQL, never Celery (`process_delivery_task`
never raises to trigger a Celery-level retry — it always returns normally,
whatever the delivery outcome), so the two counters measure genuinely
different layers and must never be read as the same thing.

`observe_delivery_terminal` records the actual `DELIVERED`/`FAILED`/`DEAD`
split — `FAILED` (retryable failure, attempt budget exhausted) and `DEAD`
(explicit non-retryable failure) are kept distinguishable, never merged.
Only `DELIVERED` ever carries an end-to-end duration
(`supportpilot_delivery_end_to_end_duration_seconds`, `created_at` ->
`delivered_at`, including any retries/backoff that occurred) — a FAILED/DEAD
delivery never fabricates one.

### Claim recovery, broker publication, redrive

`observe_delivery_claim_recovery` fires once per successful expired-claim
reclaim, from the same `_claim_row` branch that marks the abandoned worker's
orphaned attempt `ABANDONED` — one observation per reclaimed delivery,
regardless of how many recovery sweeps republished its id (the sweepers
themselves, `notifications/recovery.py`, never call any delivery metric
directly — only the claim primitive that actually changed ownership does).

`observe_delivery_broker_publication_failure` fires from
`dispatch_delivery_for_processing`'s caught broker exception, labeled by
`source` (`initial` — `create_delivery`'s own post-commit dispatch, or a
redrive's; `sweeper` — `notifications/recovery.py`'s two sweep functions,
which pass `source="sweeper"` explicitly). A publication failure never
consumes an attempt slot or touches delivery state — the delivery stays
exactly as durably persisted, recoverable by the next sweep.

`observe_delivery_redrive` fires only from `webhooks/services.py::redrive_webhook_delivery`'s
own `transaction.on_commit`, past every rejection guard (wrong status,
disabled endpoint) — a rejected redrive request never reaches it. It never
implies a new logical `Delivery` was created; the same row, same attempt
history, continues.

### Webhook-specific: response class and destination rejection

`observe_webhook_response` fires from the shared completion functions
whenever `response_status_code` is present (webhook-only — notifications
never set it), collapsed to `2xx`/`3xx`/`4xx`/`5xx`. 3xx is defined
defensively; Phase 10 never actually reaches it as a persisted delivery
outcome (`webhooks/transport.py::send_pinned_request` rejects a redirect
response itself, before the completion functions ever see a status code for
it) — the bounded set exists so a future transport change can never
silently create an unbounded label rather than being caught by this
classifier.

`observe_webhook_destination_rejection` fires from
`webhooks/services.py::handle_webhook_delivery_attempt`, at the exact point
`parse_webhook_url`/`resolve_and_validate` raise during an **actual
attempted send** — never at endpoint creation/update time
(`_best_effort_ssrf_check` never calls it), since DNS can legitimately
change between creation and send (the send-time re-validation this metric
observes is the same one that defends against DNS rebinding). `reason` is
one of `invalid_url`/`destination_blocked`/`dns_error` — drawn directly from
`webhooks.security`'s actual exception classes, never a hostname, IP, or
URL.

### Tracing: `delivery.attempt`

One `delivery.attempt` domain span per actual external attempt — wrapping
`webhooks/services.py::handle_webhook_delivery_attempt`'s
secret/DNS/sign/send sequence, and `notifications/notification_delivery.py::handle_notification_delivery_attempt`'s
provider call. Attributes are bounded: `delivery.channel`,
`attempt.number`, and the outcome `finalize_domain_span` sets at each exit
path. Never the recipient, subject, notification body, webhook URL, webhook
payload, or signing secret. A retried delivery gets a fresh span per
attempt (a new Celery task execution each time) — never one span held open
across retry backoff; the stable correlation across attempts is the
`Delivery` id itself, present in structured logs, not span parentage.

### Backlog / recovery-lag gauges — DB-derived, one deliberate collector

`supportpilot_delivery_due_count`, `supportpilot_delivery_expired_claim_count`,
and `supportpilot_delivery_oldest_due_age_seconds` are recomputed from
PostgreSQL by `observability.metrics.refresh_delivery_backlog_gauges` — two
bounded aggregate queries total (`COUNT`/`MIN` grouped by `channel` over
`notifications.selectors.due_claimable_deliveries`/`expired_claimed_deliveries`,
the same selectors the sweepers themselves use), never one query per
delivery, never a full row fetch.

**Collector architecture (deliberate, not incidental):** this function has
exactly **one** call site — `observability/views.py::metrics_view`, the
Django/Gunicorn `/metrics/` scrape path — and is never called from
`render_metrics()` itself. `render_metrics()` is also what
`config/celery_metrics.py`'s Celery-worker exposition listener calls; if the
gauge refresh lived there, every Celery worker's own metrics scrape would
independently re-run these DB queries. Keeping the refresh call in the one
Django view instead bounds the query cost to however often that endpoint is
scraped, never multiplied by worker-process count.

Every known channel is set explicitly on every refresh, including to `0` —
never left unset when a channel currently has no matching rows. This
matters because these gauges use `multiprocess_mode="mostrecent"` (not
`Gauge`'s default of summing every process's last-written value): they
represent one current global count, recomputed fresh by whichever Gunicorn
worker happens to serve a given scrape, so summing across however many
workers have ever handled `/metrics/` would silently multiply the real
value. "Most recently written, across whichever process wrote last" is the
correct aggregation here; leaving a channel unset would let a stale prior
value linger forever under that aggregation once its backlog actually
clears.

**Oldest due age** uses `next_attempt_at`, never `created_at` — a delivery
legitimately scheduled into the future by retry backoff must never inflate
this figure; only a delivery that is *actually* overdue right now
contributes. `0` (not an omitted sample) is the documented value when there
is no due backlog at all, and once this gauge has been refreshed at least
once for a channel — an absent series and a healthy "0 lag" series are easy
to conflate in a dashboard/alert expression.

**Failure isolation**: `refresh_delivery_backlog_gauges` wraps its query in
its own `try`/`except`, and `metrics_view` wraps the call to it in a second
one — a PostgreSQL error degrades those three gauges to their last-known
value; it never prevents the rest of a scrape from rendering, and it never
touches business/delivery state (the function only reads).

### Ambiguous external success remains at-least-once, never exactly-once

Phase 10's own guarantee is unchanged by Block 4 and is not weakened by
anything telemetry does: **durable at-least-once delivery**, never
exactly-once. If a sender observes a timeout after the receiver actually
processed the request, the metrics reflect the *observed* failure/retry —
never an inferred receiver-side success. A later retry that succeeds
produces a second, genuinely real `DeliveryAttempt` and a second
`supportpilot_delivery_attempts_total` observation; nothing in this registry
ever claims or implies exactly-once semantics, and the SLO document
(`docs/observability/slos.md`) states this explicitly.

### Receiver failures vs. platform failures

A customer's webhook endpoint returning `4xx`/`5xx` is a **receiver**
condition (`supportpilot_webhook_responses_total{status_class="4xx"/"5xx"}`,
and `error_category="remote_4xx"/"remote_5xx"` on the attempt-failure
counter) — not evidence of a SupportPilot platform outage. DNS/TLS/
connection/timeout failures and SSRF rejections are the platform/transport
side of the same boundary. `docs/observability/slos.md` keeps these two
views separate rather than presenting every non-2xx webhook outcome as one
undifferentiated failure rate.
