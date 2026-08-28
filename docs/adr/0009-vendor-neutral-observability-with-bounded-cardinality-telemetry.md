# ADR 0009: Vendor-neutral production observability with bounded-cardinality telemetry

## Status

Accepted (Phase 11, Block 1 — metrics foundation; extended by later blocks).

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

- No true distributed tracing (spans, cross-service trace propagation) —
  correlation is request-id/log-based and relationship-based, not a trace
  waterfall. Acceptable for this system's current single-service-plus-Celery
  topology; revisitable if a real multi-service topology emerges.
- Multiprocess Prometheus metrics require the `PROMETHEUS_MULTIPROC_DIR`
  environment variable to be set correctly, before import, in every process
  that should aggregate correctly (`config/gunicorn_conf.py` handles this
  for Gunicorn) — a real operational detail an operator must understand
  before adding metrics to a new process type (e.g. Celery workers, in a
  later block).
- Bounded-cardinality labels mean a metric alone cannot answer "which
  specific delivery/customer is affected" — that question is answered by
  correlating a metric's timestamp/outcome with structured logs and the
  database, not by widening a label. This is a deliberate trade, not an
  oversight.
