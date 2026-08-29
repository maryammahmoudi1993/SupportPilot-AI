# ADR 0009: Vendor-neutral production observability with bounded-cardinality telemetry

## Status

Accepted (Phase 11, Block 1 — metrics foundation; Block 2 — correlation-id
propagation and task-level metrics across the Celery boundary, then
extended within Block 2 by a remediation adding vendor-neutral distributed
tracing; Block 3 — Celery metrics exposition, an OTLP exporter, and agent/
LLM/tool/policy/approval/handoff domain instrumentation — see the
Amendments below).

## Amendment (Block 3): telemetry egress closed, domain instrumentation added

Block 3 closed both operational gaps the Block 1/2 amendment below left
open, and extended metrics/tracing from HTTP+Celery infrastructure to the
actual business operations Phase 11's brief always intended them to cover
("metrics must represent business operations, not merely HTTP calls").

**Celery metrics exposition** (`config/celery_metrics.py`): a prefork-safe
HTTP listener, using the same structural pattern
`config/gunicorn_conf.py` already established for Gunicorn's own
multiprocess metrics, translated onto Celery's actual process-lifecycle
signals (`worker_init` fires in the parent before the prefork pool forks
any child; `worker_process_shutdown` — despite its name — also fires in the
parent, with the dead child's pid, from
`celery.concurrency.prefork.process_destructor`). Exactly one listener
binds, in the parent, before any child exists; children never bind a port.
Loopback-only by default and off by default — see the module's own
docstring for the full security/lifecycle rationale. Proven with a genuine
cross-process test (a real subprocess writes multiprocess mmap files before
this process ever imports `observability.metrics`, then this process reads
them back via `MultiProcessCollector`), not merely a mock.

**OTLP exporter** (`observability/tracing.py`): a `BatchSpanProcessor` +
`OTLPSpanExporter` (HTTP/protobuf transport), attached only when
`OBSERVABILITY_OTLP_ENDPOINT` is configured — endpoint absent remains
Block 2's explicit local/no-export mode, never a silently-chosen default
collector. Batched/async by construction (never a synchronous network call
on the request/task thread); exporter construction or export failure both
fail open, proven by a real unreachable-collector test.

**Domain instrumentation**: `observability/metrics.py` gained agent run,
LLM provider call, tool execution, policy decision, approval, and handoff
metrics; `observability/tracing.py` gained a generic `domain_span`/
`finalize_domain_span` pair used at each of those boundaries. Every new
metric's label set was chosen the same way the original decision below
chose HTTP's `route`/Celery's `task_name`: bounded, code-owned enums only
(`AgentRunTrigger`, the actual `AgentRunStatus`/`ToolExecutionStatus`/
`ApprovalStatus` terminal sets, `ProviderError` codes, the tool registry's
own key) — never a workspace/run/execution/approval/handoff id. See
`docs/architecture/observability.md`'s "Domain instrumentation" section for
the full boundary-by-boundary rationale, including why counters are
recorded via `transaction.on_commit` (never inside the transaction being
measured) and why `WAITING_FOR_APPROVAL`/`HANDED_OFF` are handled as the
non-failure outcomes they actually are.

## Amendment (Block 2 remediation, Part B): distributed tracing added

The original decision below rejected the OpenTelemetry SDK for Block 1,
while explicitly noting the door was not closed: "this decision does not
foreclose adding OTel later behind the same metric definitions if a real
need for full distributed tracing emerges." That need emerged within Block
2 itself — request-id/log-based correlation alone could not represent a
true parent/child span relationship across the HTTP -> Celery boundary.

What changed, concretely:

* `opentelemetry-api` and `opentelemetry-sdk` are now direct dependencies
  (`observability/tracing.py` is the sole module that imports them —
  same "one call site" principle as `observability/metrics.py`).
* W3C Trace Context (`traceparent`/`tracestate`) is the propagation
  format, parsed only through OpenTelemetry's own propagator — never
  hand-rolled.
* **No exporter/span processor ships in this block.** The `TracerProvider`
  is built with no processor attached: spans are created, correctly
  parented, and give real `trace_id`/`span_id` values for propagation and
  log correlation, but are not sent anywhere. Adding a real exporter
  (OTLP or otherwise) is left to whichever future block actually needs
  spans to leave the process — not fabricated here for appearance.
* Every design constraint from the original decision below still holds
  unchanged for tracing: bounded attributes only (never a raw path, query
  string, header, or exception message), failure-open on any tracing
  error, and no new business-data persistence path.

This is additive, not a reversal — metrics remain exactly as decided
below; tracing now sits alongside them behind the same "vendor-neutral,
bounded, fail-open" design principle.

## Context

By Phase 10 the platform performs several distinct, chained production
workflows — HTTP request handling, agent orchestration, typed tool
execution, policy/approval decisions, human handoff, and durable
notification/webhook delivery with a recovery sweeper — entirely without any
way for an operator to answer basic production questions: is the API
healthy, are agent runs succeeding, are deliveries retrying more than usual,
is recovery keeping up with broker outages.

Phase 11 needs to make those workflows observable without:

- becoming a second source of business truth (PostgreSQL already is one,
  per every prior phase's architecture);
- introducing operational infrastructure disproportionate to a project at
  this scale (a Prometheus server, Grafana, Jaeger/Tempo, Loki, Kafka,
  ClickHouse, Elasticsearch, Sentry) — explicitly out of scope per the
  Phase 11 brief;
- creating a new class of security/privacy risk (metric labels or trace
  attributes that leak tenant data, secrets, or PII);
- creating a new class of production outage risk (unbounded metric
  cardinality, a metrics/tracing dependency that can take the API down).

## Decision

1. **Metrics**: use `prometheus_client`, a pure exposition-format client
   library, not a server, SDK, or vendor agent. Every metric is declared
   once, centrally, in `observability/metrics.py`.
2. **No OpenTelemetry SDK.** Distributed tracing/correlation needs are met
   instead by structured logging (`common.middleware.RequestIdMiddleware` +
   `StructuredLoggingMiddleware`, already present since an earlier phase)
   plus the application's own existing model relationships — an
   `AgentRun`/`ToolExecution`/`Delivery` id already lets an operator query
   its own causal chain in PostgreSQL. Adding a second, heavier
   instrumentation stack purely to get span objects would duplicate
   correlation Phase 11 can get from what already exists.
3. **Telemetry is never business PostgreSQL data.** No `MetricPoint`,
   `TraceSpan`, or `LogEntry` table is added. Metrics live in each process's
   memory (aggregated across processes at scrape time in production, per
   the multiprocess design below); logs and audit events keep using their
   existing, distinct persistence paths.
4. **Metric labels are drawn from small, bounded, server-owned sets only** —
   never a workspace/customer/delivery/request id, a raw URL, an exception
   message, or a provider response body. High-cardinality identifiers
   belong in logs (where they are operationally necessary and already
   permitted) and in the application's own database relationships, never in
   a metric label.
5. **Observability failures fail open.** A metrics-recording or export
   failure is caught, logged, and never allowed to affect the business
   operation it was measuring.
6. **Vendor-neutral by construction.** Prometheus exposition format is
   understood by essentially every modern metrics backend (Prometheus
   itself, Grafana Agent/Alloy, most vendors' OTLP/Prometheus bridges) — no
   vendor SDK (Datadog, New Relic, Honeycomb) is hard-coded into application
   code.

## Alternatives considered

- **OpenTelemetry SDK (metrics + tracing) from the start.** Rejected for
  Block 1: it is a substantially heavier dependency and multiprocess/export
  configuration surface than a single exposition-format client library, for
  correlation needs this phase can meet with structured logging and
  existing relationships. Not permanently ruled out — `prometheus_client`'s
  exposition format and OpenTelemetry's own Prometheus exporter are
  compatible, so this decision does not foreclose adding OTel later behind
  the same metric definitions if a real need for full distributed tracing
  emerges.
- **A custom in-house metrics/tracing protocol.** Rejected — reinventing a
  worse version of an existing, widely-supported standard for no benefit.
- **Storing telemetry in PostgreSQL** (a `MetricPoint`/`TraceSpan` table).
  Rejected — this is exactly the "generic telemetry database" the Phase 11
  brief explicitly excludes, and it would make PostgreSQL a write-heavy,
  high-volume operational log store rather than the business/reliability
  source of truth it already is.
- **Deploying a Prometheus server / Grafana / Jaeger / Loki in this repo.**
  Rejected — explicitly out of scope; this phase produces a
  scrapeable/exportable surface, not a hosted observability stack.
- **Raw request path (or another unbounded value) as a metric label**, for
  simplicity. Rejected — this is the specific cardinality-explosion failure
  mode the whole design exists to prevent; see the bounded `route`
  normalization (`"unmatched"` collapse for unresolved paths) in
  [the observability architecture doc](../architecture/observability.md#cardinality-rules).

## Consequences

**Benefits**: a small, auditable, vendor-neutral telemetry surface;
guaranteed-bounded cardinality by construction; correlation that reuses
infrastructure the application already has (request ids, structured JSON
logs, model relationships) rather than duplicating it; zero new
infrastructure services to operate; export/recording failures cannot affect
business correctness.

**Trade-offs**:

- Distributed tracing (added by the Block 2 remediation amendment above)
  gives a real span/parent relationship across the HTTP -> Celery boundary,
  but shipped no exporter — spans were not sent anywhere until Block 3
  added one (see the Block 3 amendment above), and remain unexported unless
  `OBSERVABILITY_OTLP_ENDPOINT` is actually configured.
- Multiprocess Prometheus metrics require the `PROMETHEUS_MULTIPROC_DIR`
  environment variable to be set correctly, before import, in every process
  that should aggregate correctly (`config/gunicorn_conf.py` handles this
  for Gunicorn; `config/celery_metrics.py`, added in Block 3, handles the
  equivalent for Celery workers via their own, separately-configured
  `OBSERVABILITY_CELERY_PROMETHEUS_MULTIPROC_DIR`) — a real operational
  detail an operator must understand before adding metrics to a new process
  type.
- Bounded-cardinality labels mean a metric alone cannot answer "which
  specific delivery/customer is affected" — that question is answered by
  correlating a metric's timestamp/outcome with structured logs and the
  database, not by widening a label. This is a deliberate trade, not an
  oversight.
