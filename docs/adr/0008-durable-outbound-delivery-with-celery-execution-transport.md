# ADR 0008: Durable Database-Backed Outbound Delivery with Celery as Execution Transport

- Status: Accepted
- Date: 2026-08-28

## Context

Phase 10 needed two outbound-delivery producers — asynchronous customer
notifications (email) and signed outbound webhooks for third-party
integrations — that must survive a Celery/Redis outage, a worker crash, and
an application restart without losing or silently duplicating work.

The obvious naive approach — do the provider/HTTP call synchronously inside
the request or domain-service transaction, or fire a Celery task via
`transaction.on_commit(task.delay)` and treat that task as the only record
of the work — is insufficient. A `transaction.on_commit` callback runs
after the domain transaction has already committed, so a broker failure at
that exact moment does not roll anything back — but if the callback's
`task.delay()` call is also the *only* place the pending work is recorded,
that failure permanently loses it: nothing else remembers this notification
or webhook needs to be sent, and no later process has anything to look at
to recover it. Celery's own message broker is not a durable system of
record for business intent — it is a transport for waking up a worker.

## Decision

1. **PostgreSQL is the source of truth for delivery state**, never Celery,
   never Redis. A `Delivery` row (`notifications/models.py`) is created
   transactionally, in the same commit as the domain event that produced
   it (an approval decision, a handoff, a `notification.send` tool call).
   `transaction.on_commit` is used only to *wake up* a worker as soon as
   possible after that commit — a best-effort optimization, not the
   recovery mechanism.
2. **Celery is execution transport only.** A task carries nothing but a
   delivery id and contains no business logic
   (`notifications/tasks.py`) — it delegates entirely to
   `notifications.services.process_claimed_delivery`, which is the actual
   authority over whether an attempt may proceed.
3. **Atomic PostgreSQL claiming is the concurrency primitive.**
   `select_for_update(skip_locked=True)` lets two workers (or two
   duplicate task messages) race for the same delivery safely: exactly one
   wins the claim and makes the external attempt; the other finds nothing
   claimable and no-ops. This is what makes duplicate Celery message
   delivery, redelivery after connection loss, and two Beat schedulers
   firing simultaneously all safe by construction rather than by
   coincidence.
4. **Leases + stale-worker fencing recover a crashed worker.** Every claim
   carries an expiring `lease_expires_at` and a fresh `claim_token`; a
   worker that stalls mid-attempt is eventually superseded by a reclaim,
   and its own late completion call is rejected (`StaleClaimError`)
   because the claim token it holds is no longer current. The abandoned
   worker's own in-flight `DeliveryAttempt` is marked `ABANDONED`, not
   silently overwritten.
5. **A database-owned recovery sweeper closes the broker-outage gap.**
   `notifications/recovery.py`'s two functions — `dispatch_due_deliveries`
   and `recover_expired_delivery_claims` — run on a Celery Beat schedule
   and re-publish exactly the delivery ids that are due or whose claim has
   expired. Publishing the same id from two sweepers, or from a sweeper
   racing an active worker, is always safe for the same reason two workers
   racing a claim is safe (decision 3).
6. **Bounded, deterministic exponential backoff, entirely server-owned.**
   `delay = min(base * 2^(attempt-1), max_delay)`, computed from the
   database's own `attempt_count` — never from a Celery retry counter,
   never influenced by client, provider, or a remote `Retry-After` header.
7. **At-least-once delivery with a stable logical idempotency identity is
   the guarantee — never exactly-once.** A notification's provider
   idempotency key and a webhook's `WebhookEvent.id` / `Delivery.id` /
   `Idempotency-Key` header stay identical across every retry of the same
   logical delivery, so a receiver or provider *capable* of dedup can
   collapse a duplicate. This platform does not and cannot guarantee that
   an arbitrary receiver performs that dedup — see Consequences.

## Alternatives rejected

- **Treating the Celery message itself as the durable record** (no
  database row until a worker picks it up) — rejected: a broker outage
  between "domain transaction commits" and "task is durably enqueued" has
  no recovery path at all under this design; the work is simply gone.
- **A generic event-bus/message-queue platform (Kafka, etc.)** — rejected
  as disproportionate: this system needs durable at-least-once delivery of
  a bounded, low-volume set of outbound side effects (customer emails,
  webhook calls to a workspace's own configured endpoints), not a
  high-throughput distributed log. Introducing a second infrastructure
  dependency and operational surface for that would cost more than the
  PostgreSQL-claim model it would replace, for no guarantee this design
  does not already provide.
- **A generic workflow orchestration engine** (Temporal-style) — rejected
  for the same reason: the actual state machine needed here
  (PENDING → CLAIMED → RETRY_SCHEDULED → DELIVERED/FAILED/DEAD) is small,
  fully expressible as a Django model with DB constraints, and does not
  need arbitrary long-running multi-step workflow semantics.
- **Celery's own `autoretry_for`/`self.retry()`** — rejected in favor of
  `max_retries=0` on every delivery task. Letting Celery's retry counter
  drive attempts would create a second, competing retry authority
  alongside the database's `attempt_count`/`max_attempts`, with no single
  source of truth for "how many times has this actually been tried."

## Consequences

Benefits:

- A broker outage, a worker crash at any point in an attempt's lifecycle,
  or an application restart all recover from PostgreSQL state alone — no
  in-memory queue, cache, or list is ever required for correctness.
- Duplicate task delivery, duplicate sweeper publication, and concurrent
  workers are all safe by construction, proven under real PostgreSQL
  concurrency (`threading.Barrier` against real row locks), not just
  assumed.
- `max_attempts = N` can never produce `N + 1` external calls — enforced
  by a database constraint (`attempt_count <= max_attempts`), not
  application-level bookkeeping alone.

Trade-offs:

- **Duplicate external attempts are possible after an ambiguous outcome.**
  If a remote receiver/provider accepts and processes a request but the
  sender's connection is lost before it observes the response, this
  platform correctly cannot tell the two apart from a normal failure — it
  retries. A real SMTP relay or an arbitrary webhook receiver that does
  not implement dedup on the stable identity this platform provides may
  act on that duplicate. This is inherent to at-least-once delivery over
  an unreliable network, not a defect, and is documented explicitly rather
  than hidden.
- **No global or per-endpoint delivery ordering is guaranteed.** A retry
  can be delivered after a later, unrelated event's first attempt.
  Consumers that need ordering must use the event's own timestamp/id, not
  arrival order.
- **PostgreSQL becomes a hard dependency for delivery correctness**, not
  just storage — `select_for_update(skip_locked=True)` and DB-level
  constraints are load-bearing, not incidental. This is an accepted cost
  given PostgreSQL is already this project's system of record for every
  other domain.
- **Lease/reclaim adds real state-machine complexity** (claim tokens,
  lease expiry, `ABANDONED` attempts) beyond a naive "retry N times"
  design — accepted because the alternative (no stale-worker fencing)
  allows a recovered delivery's newer, correct completion to be silently
  overwritten by a worker that stalled and woke up late.
