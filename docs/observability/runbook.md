# Operational runbook

Response guidance for the alerts in
[`deploy/observability/prometheus-rules.yml`](../../deploy/observability/prometheus-rules.yml).
No alert manager is deployed by this repository — these rules are a
deployment-compatible starting point for whatever Prometheus-compatible
system an operator points at `/metrics/`, not a claim that one is running.

Every scenario below ends with **investigate, then use the supported
service/API to act** — never a direct database write. Manual redrive uses
`webhooks/services.py::redrive_webhook_delivery` (via its API), not a raw
`UPDATE`.

## API 5xx spike (`HighApi5xxRate`)

**Signal**: elevated `supportpilot_http_requests_total{status_class="5xx"}`
rate relative to total request rate, sustained over the alert window.

**Likely causes**: a bad deploy, a database outage/exhausted connection
pool, an unhandled exception in a view, a downstream integration failure
bubbling up through a code path that does not degrade gracefully.

**First metric to inspect**:
`sum(rate(supportpilot_http_requests_total{status_class="5xx"}[5m])) by (route)`
— which route(s) are actually failing narrows this immediately (one route
= a code/deploy issue; every route = infrastructure).

**Correlate**: pull `request_id` from the structured error logs for the
affected window; the same field is on every log line the failing requests
produced (`common.middleware.StructuredLoggingMiddleware`). If tracing is
enabled, `trace_id` on the same log lines links to the corresponding span.

**DB state to verify**: `python manage.py dbshell` -> check active
connection count and any long-running queries
(`SELECT * FROM pg_stat_activity WHERE state != 'idle';`) if the failure
pattern suggests DB exhaustion — read-only inspection only.

**Remediation direction**: roll back a recent deploy if the timing
correlates; scale the database connection pool or investigate a runaway
query if DB-bound; fix and redeploy for a code-level exception. Never
restart application processes as a first response without first capturing
the `request_id`/logs above — a restart destroys the in-flight evidence.

## API latency high (`HighApiLatency`)

**Signal**: p95 `supportpilot_http_request_duration_seconds` above target
for an eligible route, sustained over the alert window.

**Likely causes**: a slow query, N+1 query pattern, an external
integration call blocking the request thread, resource contention (CPU/DB
connections) from another workload on the same infrastructure.

**First metric to inspect**: `histogram_quantile(0.95, ...) by (route)` to
isolate which route regressed; if delivery/agent routes specifically, check
whether they are doing synchronous work that should have been dispatched
instead (see the API Latency SLO's own note on eligible traffic).

**Correlate**: `trace_id` on the slow request's log lines (if tracing
enabled) shows the actual span breakdown.

**Remediation direction**: add a missing index, fix an N+1 query, or move
inline work to a `Delivery`/Celery task if a route is doing something it
should have dispatched instead.

## Agent orchestration failures (`AgentOrchestrationFailureSpike`)

**Signal**: elevated `supportpilot_agent_runs_total{outcome="failed"}` or
`outcome="budget_exceeded"` rate relative to total terminal runs.

**Likely causes**: an LLM provider outage/rate-limit
(`supportpilot_llm_requests_total{outcome!="success"}` will show this
independently), a tool handler regression, a budget configured too tightly
for the current workload.

**First metric to inspect**:
`sum(rate(supportpilot_llm_requests_total{outcome!="success"}[5m])) by (outcome)`
to rule out/in a provider-side cause before assuming an internal bug.

**Correlate**: the failing `AgentRun`'s own id (from structured logs
around the failure) links to its `AgentStep` history for the actual failure
point — never reconstructed from metrics alone.

**Remediation direction**: if provider-caused, this is expected to
self-resolve once the provider recovers — do not treat as an internal
incident unless it persists past the provider's own reported outage window.
If handler-caused, this needs a code fix, not an operational one.

## Delivery retry spike (`DeliveryRetrySpike`)

**Signal**: elevated `supportpilot_delivery_retries_total` rate for a
channel.

**Likely causes**: a downstream provider/receiver having a bad period
(webhook: customer's own endpoint degrading; notification: the email
provider rate-limiting or timing out).

**First metric to inspect**:
`sum(rate(supportpilot_delivery_attempt_failures_total[5m])) by (channel, error_category)`
— the `error_category` breakdown says immediately whether this is
receiver-side (`remote_5xx`) or platform-side (`timeout`/`connection`/
`dns`/`tls`/`internal`).

**Correlate**: for webhooks, cross-reference with
`supportpilot_webhook_responses_total{status_class="5xx"}` for the same
window.

**DB state to inspect (read-only)**: via Django shell or the workspace API
— deliveries currently `RETRY_SCHEDULED` for the affected channel/endpoint,
their `last_error_code`, and `attempt_count` vs `max_attempts` (how close to
exhaustion).

**Remediation direction**: receiver-side — this is expected to be the
customer's problem; consider notifying them if it persists. Platform-side —
treat like any other transport/infrastructure incident.

## Oldest due delivery age high (`OldestDueDeliveryTooOld`)

**Signal**: `supportpilot_delivery_oldest_due_age_seconds` above the
[recovery lag target](slos.md#6-recovery-lag) (120s), sustained.

**Likely causes**: Celery workers not running/crashed, broker (Redis)
unavailable, Beat scheduler not dispatching the sweeper tasks, or a
backlog genuinely larger than current worker capacity can drain.

**First metric to inspect**: `supportpilot_delivery_due_count` alongside
the age gauge — a growing count *and* growing age together means capacity
is the issue; a flat count with growing age on one specific delivery means
something is stuck.

**Correlate**: check
`supportpilot_delivery_broker_publication_failures_total{source="sweeper"}`
for the same window — if that is also elevated, the sweepers are running
but cannot reach the broker, which is a different root cause than "sweepers
aren't running at all".

**DB state to inspect (read-only)**: PENDING/RETRY_SCHEDULED rows with
`next_attempt_at` far in the past — how many, and how old the oldest one
actually is, via the workspace-scoped delivery listing API.

**Remediation direction**: verify Celery Beat and worker processes are
actually running (infrastructure-level check, outside this application);
verify broker connectivity; if capacity-bound, scale worker count. Never
manually flip a delivery's status — the recovery sweepers themselves are
the supported remediation path once the underlying infrastructure issue is
fixed; they will pick the backlog back up automatically.

## Expired claim spike (`ExpiredClaimSpike`)

**Signal**: elevated `supportpilot_delivery_claim_recoveries_total` rate.

**Likely causes**: worker crashes mid-attempt, a handler taking longer
than `DELIVERY_CLAIM_LEASE_SECONDS` (default 300s) to complete, or the
lease duration configured too short for genuinely slow external calls.

**First metric to inspect**:
`supportpilot_delivery_attempt_duration_seconds` p99 for the affected
channel — if attempts are legitimately taking close to the lease duration,
the lease is too short, not the workers unhealthy.

**Correlate**: worker process logs/restarts around the same window (outside
this application's own telemetry — check the deployment platform's own
worker health signals).

**Remediation direction**: if worker crashes, investigate why (OOM, an
unhandled exception escaping the task boundary); if legitimately slow
attempts, consider raising `DELIVERY_CLAIM_LEASE_SECONDS`. This is
**operational**, not necessarily SLO-breaching on its own — see the
recovery-lag SLO's own note that expired claims are expected to be rare but
are an alert signal, not an SLO target in themselves.

## Broker publication failures (`BrokerPublicationFailures`)

**Signal**: elevated
`supportpilot_delivery_broker_publication_failures_total` rate, either
`source`.

**Likely causes**: Redis (the Celery broker) unavailable or overloaded.

**First metric to inspect**: the `source` label — `initial` failures alone
(sweepers not yet run) versus `sweeper` failures too (sustained outage) is
the fastest signal of severity.

**Correlate**: application logs for `delivery_dispatch_failed` around the
same window — this event never includes the raw broker exception text
(see `notifications/services.py::dispatch_delivery_for_processing`), so
broker-side logs/monitoring are the actual next step for root cause.

**Remediation direction**: this is infrastructure (Redis), not an
application-code issue. Deliveries are not lost during an outage — they
stay `PENDING`/`RETRY_SCHEDULED`, unconsumed, and the recovery sweepers
drain the backlog automatically once the broker recovers (see
[`OldestDueDeliveryTooOld`](#oldest-due-delivery-age-high-oldestduedeliverytooold)
above for confirming that drain actually happens).

## Webhook receiver 5xx spike (`WebhookReceiver5xxSpike`)

**Signal**: elevated
`supportpilot_webhook_responses_total{status_class="5xx"}` rate.

**This is a receiver-side signal, not necessarily a SupportPilot
incident** — see [`docs/observability/slos.md`](slos.md#7-webhook-receiverplatform-health).
Still worth surfacing: a customer's own endpoint degrading is operationally
relevant even though it is not this platform's fault.

**First metric to inspect**: whether the 5xx rate is concentrated on one
endpoint (would require per-workspace investigation via the API, since
`endpoint_id` is deliberately never a metric label) or broad.

**Remediation direction**: this platform's own responsibility is limited
to correct retry/backoff behavior (already Phase 10's job) and clear
operator/customer-facing visibility (the delivery/attempt history API) —
not fixing the customer's endpoint.

## Webhook terminal failure spike (`WebhookTerminalFailureSpike`)

**Signal**: elevated
`supportpilot_delivery_terminal_total{channel="webhook", outcome="dead"}`
rate.

**Likely causes**: a receiver returning a persistent non-retryable status
(most 4xx), a signing/configuration issue on the customer's side, or a
platform-side non-retryable classification bug.

**First metric to inspect**:
`supportpilot_delivery_attempt_failures_total{channel="webhook"}` broken
down by `error_category` — `remote_4xx` implicates the receiver;
`configuration`/`internal` implicates this platform.

**Remediation direction**: receiver-caused — this is expected to require
the customer to fix their endpoint; a manual redrive (via the supported
API) is appropriate once they confirm a fix. Platform-caused — a code
fix, then redrive the affected deliveries once deployed.

## Webhook destination rejection spike (`WebhookDestinationRejectionSpike`)

**Signal**: elevated `supportpilot_webhook_destination_rejections_total`
rate.

**Likely causes**: a customer misconfigured an endpoint URL, a customer's
DNS now resolves somewhere unsafe (a real DNS-rebinding attempt, or simply
a broken DNS record), or — the concerning case — a customer's *legitimate*
endpoint hostname was compromised/repointed to an internal address.

**First metric to inspect**: the `reason` label —
`invalid_url`/`destination_blocked`/`dns_error` — narrows which validation
layer is rejecting.

**Remediation direction**: this is the security control working as
designed; do **not** weaken or bypass it to "fix" the alert. If a spike is
concentrated and sudden (rather than steady background noise from
already-misconfigured endpoints), treat it as a potential security signal
worth investigating which endpoint(s) are involved (via the workspace API,
never by adding a metric label) before assuming it is benign misconfigured
DNS.

## Redrive DB state checks (read-only reference)

The following describes what an operator investigates, conceptually, via
the supported workspace-scoped API/selectors — never raw SQL, never a
direct `UPDATE`:

- **PENDING due**: `notifications.selectors.due_claimable_deliveries`
  (status `PENDING`, `next_attempt_at <= now`).
- **RETRY_SCHEDULED due**: the same selector also includes
  `RETRY_SCHEDULED` rows whose `next_attempt_at` has arrived.
- **CLAIMED expired**: `notifications.selectors.expired_claimed_deliveries`
  (status `CLAIMED`, `lease_expires_at <= now`).
- **FAILED** / **DEAD**: terminal, exhausted deliveries — eligible for
  manual redrive via `webhooks/services.py::redrive_webhook_delivery`
  (through its API), which extends `max_attempts` and reopens the same
  logical row rather than creating a new one. Never reset a delivery's
  status directly in the database — the redrive path is what re-validates
  the endpoint, preserves attempt history, and re-enters the durable
  claim/retry state machine correctly.
