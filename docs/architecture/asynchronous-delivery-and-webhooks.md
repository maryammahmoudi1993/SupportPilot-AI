# Asynchronous Delivery and Outbound Webhooks

Phase 10 adds durable, database-backed asynchronous delivery for two
producers — customer notifications (email) and signed outbound webhooks —
sharing one delivery state machine and recovery mechanism. See
[ADR 0008](../adr/0008-durable-outbound-delivery-with-celery-execution-transport.md)
for why this shape was chosen over a synchronous call, a bare
`transaction.on_commit(task.delay)`, or a generic event-bus/workflow
platform.

## Delivery architecture

```text
Domain transaction (approval decision, handoff, notification.send)
        |
        v
Delivery + channel-specific row committed together, atomically
(notifications.models.Delivery / NotificationDelivery / webhooks.models.WebhookEvent+WebhookDelivery)
        |
        v
transaction.on_commit -> best-effort Celery publication
        |
        v
Worker: PostgreSQL atomic claim (select_for_update(skip_locked=True))
        |
        v
Channel handler: external attempt (email provider / signed HTTP request)
        |
        v
DELIVERED | RETRY_SCHEDULED | FAILED | DEAD
        |
        v
Recovery sweeper (Celery Beat, every DELIVERY_SWEEP_INTERVAL_SECONDS)
re-publishes anything due or with an expired claim lease
```

PostgreSQL — not Celery, not Redis — is the sole authority for delivery
state. Celery is disposable execution transport: a duplicated, redelivered,
or entirely lost task message can never corrupt or duplicate what is
recorded in the database.

### Claim / lease model

A `Delivery` moves through `PENDING → CLAIMED → (RETRY_SCHEDULED →)*
{DELIVERED | FAILED | DEAD}`. Claiming is the concurrency primitive:

- `select_for_update(skip_locked=True)` lets two workers (or a duplicate
  Celery message, or a sweeper racing an active worker) attempt the same
  row without blocking each other — exactly one wins.
- Every claim carries a fresh `claim_token` (UUID) and an expiring
  `lease_expires_at`. Only the holder of the *current* token may complete
  the delivery (`StaleClaimError` otherwise).
- A `Delivery` with an expired lease is reclaimed by
  `reclaim_expired_delivery` (Block 1) or the recovery sweeper's
  publication of it (Block 4). Reclaiming issues a brand-new token and
  marks the abandoned worker's own in-flight `DeliveryAttempt` `ABANDONED`
  — never left ambiguously "in progress" forever, and never silently
  overwritten as succeeded/failed.
- A stale worker that eventually does call back in (success or failure) is
  rejected outright; it can never overwrite a newer, already-recorded
  outcome.

### Attempt history

Every claim creates exactly one `DeliveryAttempt` row, numbered
monotonically and immutable once written (`SUCCEEDED`/`FAILED`/`ABANDONED`
are terminal per-attempt states). `attempt_count <= max_attempts` is a
database constraint, not just application logic — the actual external call
count for a bounded `max_attempts = N` can never exceed `N`.

### Recovery

Two Celery Beat tasks, sharing one configurable interval
(`DELIVERY_SWEEP_INTERVAL_SECONDS`, default 30s), close every recovery gap:

- `dispatch_due_deliveries` — re-publishes `PENDING`/`RETRY_SCHEDULED`
  deliveries whose `next_attempt_at` has arrived. This is what recovers a
  delivery whose only publication attempt (the `transaction.on_commit`
  callback) failed because the broker was down at that instant.
- `recover_expired_delivery_claims` — re-publishes `CLAIMED` deliveries
  whose lease has expired (a crashed or stalled worker).

Publishing the same delivery id more than once — from two sweepers, or a
sweeper racing an active claim — is always safe: publication is not an
ownership operation, only claiming is. Recovery depends only on
PostgreSQL state; no in-memory queue, cache, or list is required for a
freshly-restarted process to recover exactly the same work a long-running
one would.

## Delivery guarantee

**Durable at-least-once delivery with a stable logical idempotency
identity — never exactly-once.**

If a remote receiver/provider accepts and processes a request but the
sender's connection is lost before it observes a response, this platform
cannot distinguish that from an ordinary failure and correctly retries.
The stable identity below lets a receiver capable of dedup collapse the
duplicate — this platform provides that identity, but cannot force an
arbitrary receiver or a real SMTP relay without server-side dedup to
actually use it:

| Channel      | Stable across every retry                                          |
|--------------|----------------------------------------------------------------------|
| Notification | provider idempotency key, frozen recipient/subject/body snapshot   |
| Webhook      | `WebhookEvent.id`, `Delivery.id`, `Idempotency-Key` header, raw event body bytes |

Not stable, and not required to be — fresh per actual attempt:
`X-SupportPilot-Timestamp` and `X-SupportPilot-Signature` (see Signing,
below).

No global or per-endpoint delivery ordering is promised. A retry can be
delivered after a later, unrelated event's first attempt; consumers that
need ordering should use the event's own id/timestamp, never arrival
order.

## Retry / backoff

```text
delay_seconds = min(base_delay_seconds * 2 ** (attempt_number - 1), max_delay_seconds)
```

computed from the delivery's own `attempt_count` — never a Celery retry
counter (`max_retries=0` on every delivery task; no `autoretry_for`).

- `DELIVERY_RETRY_BASE_DELAY_SECONDS` (default 30) / `DELIVERY_RETRY_MAX_DELAY_SECONDS`
  (default 3600) are server-owned settings; no client, model, provider, or
  remote `Retry-After` header can influence them. `Retry-After` is
  currently ignored entirely.
- No jitter — a deliberate simplicity choice (documented in
  `notifications/backoff.py`), not an oversight.
- A retryable failure with attempts remaining schedules a
  `RETRY_SCHEDULED` retry; retries exhausted terminates as `FAILED`;
  a failure explicitly classified non-retryable terminates as `DEAD`
  regardless of remaining budget. Both are terminal — neither is ever
  automatically resurrected by the recovery sweeper.
- An attempt abandoned by an expired lease becomes `ABANDONED`
  (`AttemptStatus.ABANDONED`) — distinct from `FAILED`, since the sender
  never actually learned an outcome for it.

## Notifications

- `notification.send` durably enqueues (`NotificationDelivery` +
  `Delivery`) and returns immediately — it never calls a provider
  synchronously.
- The recipient/subject/body snapshot is frozen at creation time; every
  retry sends that exact snapshot, never a value re-read from a
  since-mutated `Customer` record.
- A replayed `notification.send` call for the same `ToolExecution` reuses
  the existing `NotificationDelivery` — never a second logical
  notification.
- The provider idempotency key is stable across every attempt, letting a
  provider capable of server-side dedup collapse a retry after an
  ambiguous timeout.
- Failure classification reuses the existing Phase 7 `IntegrationError`
  taxonomy (`.code`/`.retryable`) — never a second classifier.

## Webhooks

- `WebhookEndpoint` — workspace-scoped destination configuration: name,
  URL, status (`ACTIVE`/`DISABLED`), a server-validated
  `subscribed_event_types` list, and an encrypted signing secret
  (reusing `integrations.crypto`, never a second encryption
  implementation).
- `WebhookEvent` — one immutable, safe-fields-only snapshot of a domain
  occurrence. Never a live reference to mutable business state; the
  payload is frozen at creation and unaffected by any later mutation of
  its source record.
- `WebhookDelivery` — the one-to-one link between a `Delivery` and one
  `(endpoint, event)` pair; a database `UniqueConstraint` on that pair is
  the fanout-dedup invariant.
- Implemented event types today: `approval.requested`, `approval.approved`,
  `approval.rejected`, `approval.expired`, `handoff.created`. No other
  event type is implemented or emitted.

### Signing

HMAC-SHA256 over `f"{timestamp}." + raw_body`, where `raw_body` is the
exact canonical JSON bytes sent and never re-serialized between signing
and transport. Headers sent with every request:

- `X-SupportPilot-Event-Id`, `X-SupportPilot-Delivery-Id`
- `X-SupportPilot-Timestamp` — fresh, real-time per actual attempt
- `X-SupportPilot-Signature` — `v1=<hex hmac>`, recomputed from that
  attempt's own timestamp; never reused across attempts
- `Idempotency-Key` — the `Delivery.id`, stable across every attempt

See [Webhook receiver verification](../security/webhook-receiver-verification.md)
for how a receiver should verify these.

### Redrive

Manual redrive (`POST .../deliveries/{id}/redrive/`, support_manager or
above) is the only way to give a terminal (`FAILED`/`DEAD`) webhook
delivery further attempts. It:

- reuses the exact same logical `WebhookEvent`/`WebhookDelivery`/`Delivery`
  row — never creates a second event;
- extends `max_attempts` by a bounded server-owned allowance
  (`WEBHOOKS_REDRIVE_ATTEMPT_ALLOWANCE`, default 3) rather than resetting
  `attempt_count` — the next attempt continues the same monotonic
  numbering, and every historical `DeliveryAttempt` stays untouched;
- is rejected outright (no state change) for anything other than a
  terminal, exhausted delivery — an active claim, `DELIVERED`, or a
  delivery still pending its own scheduled retry;
- is rejected before any state mutation if the endpoint is currently
  `DISABLED` — zero network calls;
- never bypasses the next actual attempt's independent DNS/SSRF
  revalidation or current-secret signing — an endpoint whose destination
  has since become private, or whose secret has since rotated, is handled
  exactly as any other send-time attempt would be;
- records a `webhook_delivery.manually_redriven` audit event, only after
  the state transition actually succeeds.

## SSRF and outbound transport security

See [Webhook outbound security](../security/webhook-outbound-security.md)
for the full detail. Summary: HTTPS required by default; a fail-closed
global-routability allowlist (not an incomplete blacklist) rejects every
non-public destination; DNS is resolved fresh before every attempt and
every resolved address must be safe or the whole attempt is rejected; the
connection is pinned to the pre-approved IP literal while TLS SNI,
certificate hostname verification, and the `Host` header all still use the
original hostname; redirects are never followed; timeouts are bounded.

## RBAC and tenancy

- Every workspace-scoped webhook query resolves a foreign id to `None`
  (404), never leaking existence.
- Endpoint/delivery mutation (create/update/disable/rotate-secret/redrive)
  requires `support_manager`/`admin`/`owner`, re-derived from the live
  `WorkspaceMembership` on every request — never a cached or JWT-carried
  role claim. A membership demoted mid-session is denied on its very next
  privileged request, without a new token.
- Read access to endpoint/delivery listings is any active workspace
  member; the response never includes the signing secret.

## Read-fresh-then-act boundaries (honest limitations)

Two operations are "read the current state, then act" rather than
atomically locked against a concurrent change:

- **Endpoint disable vs. an in-flight send.** The handler reloads the
  endpoint's status immediately before deciding whether to send. If a
  disable commits before that read, the send never happens. If a send is
  already in flight, disabling cannot retroactively cancel it — this
  implementation makes no claim of in-flight cancellation.
- **Secret rotation vs. an in-flight send.** The active secret is loaded
  fresh at the start of each attempt. A rotation that commits before that
  read is used; a request already signed before rotation commits
  legitimately uses the prior secret. The event body itself is unaffected
  either way — it was already frozen at `WebhookEvent` creation.

Both are deliberate, documented boundaries, not defects.
