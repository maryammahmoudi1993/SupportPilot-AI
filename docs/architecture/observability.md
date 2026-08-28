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
one of `2xx`/`3xx`/`4xx`/`5xx`.

`observability/middleware.MetricsMiddleware` records both metrics for every
completed request, after `common.middleware.StructuredLoggingMiddleware` in
`MIDDLEWARE` — a recording failure is caught and logged, never allowed to
fail the actual HTTP response (see [Failure isolation](#failure-isolation)).
The metrics endpoint itself (`route == "metrics"`) is excluded from these
metrics so scraping it does not create an ever-growing self-referential
entry in its own output.

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
- `child_exit` runs whenever a worker exits and immediately discards that
  worker's files, so a scrape after a worker restart never keeps
  double-counting a dead process's last-known values.

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

Phase 11 Block 1 does not add distributed tracing or an OpenTelemetry SDK
(see [ADR 0009](../adr/0009-vendor-neutral-observability-with-bounded-cardinality-telemetry.md)
for why). Correlation across a request today already exists through:

- `request.request_id` (`common.middleware.RequestIdMiddleware`), present on
  every structured log line the request produces
  (`common.middleware.StructuredLoggingMiddleware`).
- The existing model relationships an operator can already query — an
  `AgentRun`, `ToolExecution`, or `Delivery` id already links back to its
  workspace and, transitively, to the request that produced it.

Block 2 hardens and extends this path explicitly across the Celery boundary;
this document's [Trace/log correlation](#tracelog-correlation) section will
grow to describe that once it lands.
