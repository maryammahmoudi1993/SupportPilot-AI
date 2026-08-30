# Service level objectives

These are **defined operational objectives**, not historically measured
production guarantees. This platform has not accumulated production traffic
history; every target below is a starting point chosen for consistency with
this codebase's own configured behavior (retry backoff, sweep interval,
attempt budgets) — expect to revise them once real production data exists.

Every SLI here is derived exclusively from metrics already implemented in
`observability/metrics.py` (Phase 11 Blocks 1-4). No SLO in this document
requires a metric that does not exist.

## 1. API availability

**SLI**: the fraction of eligible HTTP requests that do **not** receive a
5xx response.

```text
1 - ( sum(rate(supportpilot_http_requests_total{status_class="5xx"}[30d]))
      / sum(rate(supportpilot_http_requests_total[30d])) )
```

**Eligible traffic**: every HTTP request the application handles, **except**
`/health/`, `/ready/`, and `/metrics/` (excluded by the same route-name
filter `observability/middleware.py` already applies before recording — see
`docs/architecture/observability.md`). A normal 4xx client error (bad
request, not found, forbidden, validation failure) is **not** counted as an
availability failure — only 5xx is.

**Target**: 99.9% over a rolling 30-day window.

**Exclusions**: `/health/`, `/ready/`, `/metrics/`.

**Interpretation**: this is an operational target for the platform's own
correctness under normal load, not a contractual commitment and not a
claim about any period that has already elapsed.

**Known limitations**: no traffic-volume floor is defined — a workspace
generating very few requests in a given window can swing this ratio sharply
on a single 5xx. A production alert (below) uses a windowed rate with an
implicit minimum-volume expectation rather than this raw 30-day ratio.

## 2. API latency

**SLI**: p95 latency of eligible synchronous API requests.

```text
histogram_quantile(0.95,
  sum(rate(supportpilot_http_request_duration_seconds_bucket[5m])) by (le))
```

**Eligible traffic**: the same exclusions as availability
(`/health/`/`/ready/`/`/metrics/`). Routes that dispatch background work
(delivery creation, agent-run execution) and return immediately are
included — their *own* response time is what this measures; the
asynchronous work itself is covered by the agent-orchestration and
delivery-latency SLOs below, never folded into this one.

**Target**: p95 < 500ms.

**Rationale**: `HTTP_REQUEST_DURATION_SECONDS`'s own bucket set
(`observability/metrics.py`) tops out its finer-grained buckets around 1s,
consistent with a synchronous-request-shaped workload; 500ms is a
starting/reviewable target, not derived from measured history.

**Exclusions**: `/health/`, `/ready/`, `/metrics/`; any route whose own
work is inherently long-running is expected to dispatch and return quickly
rather than block — if a route violates that, its presence here would
already be a signal to fix the route, not to raise this target.

## 3. Agent orchestration outcome

**SLI**: the fraction of terminal `AgentRun`s that reach an outcome the
platform itself did not cause.

```text
non_platform_failure = succeeded + handed_off + cancelled
platform_failure     = failed + budget_exceeded

SLI = non_platform_failure / (non_platform_failure + platform_failure)
```

using `supportpilot_agent_runs_total{outcome}`.

**Semantics, deliberately**:

- `WAITING_FOR_APPROVAL` is **not terminal** — `AGENT_RUN_TERMINAL_STATUSES`
  excludes it, and no code path ever records it as an outcome (see
  `docs/architecture/observability.md`). It never enters this ratio's
  denominator at all.
- `handed_off` is a successful, intentional escalation outcome — counted
  with `succeeded`, never with `failed`.
- `cancelled` is counted as non-platform-failure: every `cancel_agent_run`
  call in this codebase originates from an explicit actor decision (a user
  or an operator), never from an internal fault path — a cancelled run is
  not evidence the platform malfunctioned.
- `failed`/`budget_exceeded` are the platform's own reliability signal:
  a genuine runtime failure, or a run that exhausted its configured budget
  without completing.

**Target**: 99% non-platform-failure ratio over a rolling 7-day window.

**Exclusions**: none beyond the terminal-status set itself.

**Interpretation**: an operational target for agent runtime health, not a
claim about model quality or business-outcome correctness.

## 4. Durable delivery success

Two deliberately separate views — see
["Receiver vs. platform failures"](#receiver-vs-platform-failures) below for
why they must not be merged.

### 4a. Delivery completion ratio

**SLI**: the fraction of terminal deliveries that reach `DELIVERED`.

```text
sum(supportpilot_delivery_terminal_total{outcome="delivered"})
/ sum(supportpilot_delivery_terminal_total)
```

grouped by `channel` where useful. Includes every terminal outcome
regardless of cause — a receiver's own persistent 4xx counts against this
view, same as a platform-side DNS failure.

**Target**: 95% over a rolling 7-day window, per channel.

### 4b. Platform-attributable delivery failure ratio

**SLI**: the fraction of failed attempts attributable to the platform's own
transport/configuration layer, not the receiver.

```text
platform_categories = timeout ∪ connection ∪ dns ∪ tls ∪ internal ∪ configuration ∪ auth
platform_failures = sum(supportpilot_delivery_attempt_failures_total{error_category in platform_categories})
total_failures     = sum(supportpilot_delivery_attempt_failures_total)

SLI = 1 - (platform_failures / total_failures)
```

`error_category` values `remote_4xx`/`remote_5xx`/`blocked_destination` are
deliberately **excluded from the platform-attributable numerator**: a
receiver's own error response is a receiver condition (and
`blocked_destination` is the platform correctly refusing an unsafe
destination — a security control operating as designed, not a platform
defect).

**Target**: 99% over a rolling 7-day window.

**Exclusions**: `redrive`d attempts are counted like any other attempt —
redrive does not get its own carve-out.

**Interpretation**: 4a answers "is the customer's business event actually
arriving"; 4b answers "when it doesn't, is that our fault". A dashboard
showing only 4a would hide a receiver-caused failure spike as if it were a
platform problem — 4b exists specifically so it is not.

## 5. Delivery latency

**SLI**: end-to-end delivery latency, `Delivery` creation to `DELIVERED`.

```text
histogram_quantile(0.95,
  sum(rate(supportpilot_delivery_end_to_end_duration_seconds_bucket[1h])) by (le, channel))
```

**Target**: p95 < 5 minutes for `webhook`; p95 < 10 minutes for
`notification` (email-medium provider latency is typically higher-variance
than a direct HTTP POST).

**Exclusions**: a delivery still in progress (not yet `DELIVERED`) never
contributes a sample — this measures completed deliveries only. A delivery
that ends `FAILED`/`DEAD` never fabricates an end-to-end duration either
(see `docs/architecture/observability.md`).

**Interpretation**: this includes retry backoff time by design — a
delivery that needed two retries before succeeding has a legitimately
longer end-to-end duration than one that succeeded on attempt 1. It is
**not** attempt duration (`supportpilot_delivery_attempt_duration_seconds`,
a separate, tighter metric for the external call itself).

## 6. Recovery lag

**SLI**: how far behind the recovery/execution pipeline is running.

```text
max(supportpilot_delivery_oldest_due_age_seconds) by (channel)
```

**Target**: oldest due age < 120 seconds under normal operation.

**Rationale**: `DELIVERY_SWEEP_INTERVAL_SECONDS` defaults to 30 seconds
(`config/settings.py`). A single-sweep-interval target (30s) would be
undefensibly tight — normal worker startup lag, a slow individual attempt
holding up the next claim briefly, or ordinary scheduling jitter can
legitimately push a due delivery's age past one interval without indicating
a real problem. 120 seconds is **four** sweep intervals — a threshold that
tolerates ordinary jitter while still catching genuine backlog growth
(a stalled worker fleet, a broker outage, a stuck claim) within a few
minutes.

**Exclusions**: none — this is a pure backlog-lag signal, not
receiver-attributable.

**Interpretation**: `0` (not an omitted sample) means no due backlog exists
at the moment of the scrape that produced the sample — see
`docs/architecture/observability.md`'s gauge-semantics note.

## 7. Webhook receiver/platform health

Not a single SLO — a deliberately split pair, mirroring [section 4](#4-durable-delivery-success):

- **Receiver health** (not a SupportPilot reliability signal):
  `supportpilot_webhook_responses_total{status_class="4xx"/"5xx"}` and
  `error_category="remote_4xx"/"remote_5xx"` on the attempt-failure counter.
  Tracked and alertable (a customer's own endpoint degrading is worth
  surfacing), but never rolled into the platform SLIs above.
- **Platform/transport health** (a genuine SupportPilot signal): `dns`,
  `tls`, `connection`, `timeout`, and `blocked_destination` (SSRF rejection
  — the security control working, still worth watching for a spike, e.g. a
  misconfigured or compromised endpoint) categories, covered by
  [4b](#4b-platform-attributable-delivery-failure-ratio) above.

## Known limitations across every SLO in this document

- **No historical baseline.** Every target is a starting point, not a
  measured number — see the top of this document.
- **Ambiguous external success remains at-least-once, never exactly-once**
  (Phase 10's own documented guarantee, unchanged by Block 4's
  instrumentation). A sender-observed timeout after the receiver actually
  processed the request produces a real observed-failure metric sample and
  a real subsequent retry attempt; no SLI in this document treats that as
  evidence of exactly-once delivery, and none of the targets above assume
  it.
- **Small-sample volatility.** None of the ratios above define a minimum
  traffic floor; a low-volume window can swing sharply on one event. Alert
  rules (`docs/observability/runbook.md` and the example rule file) use
  windowed rates rather than raw long-window ratios specifically to reduce
  (not eliminate) this.
