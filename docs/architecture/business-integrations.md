# Business Tooling and External Integrations

Phase 7 connects the Phase 6 typed tool execution boundary to real business
capabilities — customer/order/payment/calendar/ticket/notification — through
narrow, typed, provider-independent adapters. It does **not** add policy or
approval; see [Phase 8 boundary](#phase-8-boundary) below.

## Architecture

```text
Agent Runtime
    |
    v
tools.execution.execute_tool          (Phase 6 — unchanged)
    |
    v
integrations.tools.<handler>          (business tool: typed in/out, tenant-scoped)
    |
    v
integrations.services.<operation>     (connection resolution, credential
    |                                   decryption, two-layer timeout,
    |                                   health tracking)
    v
integrations.providers.base.<Protocol> (PaymentProvider / CalendarProvider /
    |                                   NotificationProvider / OrderProvider)
    v
integrations.providers.factory        (fake-by-default, live-opt-in)
    |
    +--> providers.fakes.*             (deterministic, offline — default)
    +--> providers.stripe_provider     (real, test-mode only)
    +--> providers.google_calendar     (real, service-account only)
    +--> providers.email_provider      (real, SMTP)
    +--> providers.demo_commerce       (the only OrderProvider — no live vendor)
```

Every business tool (`customer.lookup`, `order.lookup`, `shipment.lookup`,
`payment.lookup`, `payment.refund`, `calendar.check_availability`,
`calendar.create_booking`, `ticket.create`, `ticket.update`,
`notification.send`) is a `tools.contracts.Tool` registered into the *same*
`tools.registry` as the Phase 6 demo tools, and runs through the *same*
`tools.execution.execute_tool` — there is no second execution path. This is
non-negotiable: an LLM never reaches a vendor SDK directly.

## Provider boundary

Application/domain code depends only on the typed protocols in
`integrations/providers/base.py` (`PaymentProvider`, `CalendarProvider`,
`NotificationProvider`, `OrderProvider`) and their normalized result types
(`NormalizedPayment`, `NormalizedRefund`, `AvailabilitySlot`,
`NormalizedBooking`, `NormalizedNotification`, `NormalizedOrder`,
`NormalizedShipment`). No `stripe.*`, `googleapiclient.*`, or `smtplib.*`
type crosses that boundary. Every adapter maps vendor exceptions to
`integrations.errors.IntegrationError` subclasses (never a raw SDK
exception) — see [Error taxonomy](#error-taxonomy).

`integrations.providers.factory` resolves fake vs. real per provider type,
gated by `INTEGRATIONS_LIVE_PROVIDERS_ENABLED` (default `False`). Every
normal test/CI/dev path uses the deterministic fakes in
`integrations/providers/fakes.py`; a real adapter is only ever constructed
when explicitly enabled. There is no live-credential requirement anywhere in
the default test suite.

`integrations.providers.demo_commerce.DemoCommerceProvider` is the *only*
`OrderProvider` implementation — the repository has no real order-management
system, so this is a deterministic, production-shaped adapter (dataset lives
in the owning `IntegrationConnection.configuration`) rather than a live
vendor integration pretending to be one.

## Credential storage

`IntegrationConnection.encrypted_credentials` is a `cryptography.fernet`
token (`integrations/crypto.py`), never plaintext. `MultiFernet` gives free
key rotation: new ciphertext always uses the first key in
`INTEGRATIONS_CREDENTIAL_ENCRYPTION_KEYS`; decryption tries every configured
key, so an old ciphertext keeps working after a new key is prepended. The
default key is a fixed development value (same pattern as `SECRET_KEY`) —
**must** be overridden with a real secret in any deployment.

Plaintext credentials only ever exist inside
`integrations.services._execute_provider_call`'s local scope, immediately
before a provider call, and are explicitly `del`eted afterward. No view,
serializer, or model `__str__` decrypts credentials. Every API response is
built from `IntegrationConnectionSerializer`, which never includes
`encrypted_credentials`; credential input is accepted only through
dedicated write-only create/rotate serializers.

## Connection model

One `IntegrationConnection` per `(workspace, provider)` (database
`UniqueConstraint`) — the simplest form of section 71's "one active
connection per provider" option. A business tool never accepts a connection
identifier as an argument; it always resolves its own workspace's
connection for its provider server-side
(`integrations.selectors.resolve_connection_for_tool`).

Status lifecycle (`IntegrationConnectionStatus`): `active`, `disabled`,
`invalid_credentials`, `degraded`. `disabled` is the only status a human
sets directly (enable/disable API); `invalid_credentials`/`degraded` are
derived automatically by `integrations.services._record_health` from the
class of error the last provider call raised — an authentication/permission
failure marks `invalid_credentials`, a rate-limit/timeout/temporary-outage
marks `degraded`, and a subsequent success clears either back to `active`.
A `disabled` connection is never touched by this — it stays disabled until a
human re-enables it, and business tools fail with `integration_disabled`
*before* any provider call.

## Error taxonomy

`integrations/errors.py` defines a stable, safe error taxonomy
(`IntegrationNotConfiguredError`, `IntegrationDisabledError`,
`IntegrationAuthenticationFailedError`, `IntegrationRateLimitedError`, ...,
plus business-specific errors like `PaymentNotFoundError` and
`CalendarSlotUnavailableError`). `integrations.tools.IntegrationToolError`
bridges one of these into `tools.errors.ToolError` at the tool-handler
boundary, so it flows through Phase 6's *existing* persistence, redaction,
and retry-classification machinery unchanged.

Retry classification is split by risk: read tools use
`READ_RETRYABLE_CODES` (rate-limited, temporarily-unavailable, *and*
timeout); `payment.refund`, `calendar.create_booking`, and
`notification.send` use the narrower `WRITE_RETRYABLE_CODES` (rate-limited,
temporarily-unavailable only) — a provider timeout on a financial or
side-effecting write is **never** auto-retried, because the outcome is
genuinely ambiguous (see [Idempotency](#idempotency)).

## Idempotency

For every side-effecting operation (`payment.refund`,
`calendar.create_booking`, `notification.send`), the provider-level
idempotency key is derived as `f"{tool_key}:{context.tool_execution_id}"`.
Because Phase 6 resets the *same* `ToolExecution` row back to `PENDING` (and
therefore keeps the same `tool_execution_id`) when a caller retries with the
same application-level `idempotency_key`, this provider key is stable across
retries of one logical action — never regenerated per attempt.

This is what makes the "ambiguous timeout" scenario safe: if a provider
processes a refund/booking/send but the client only observes a timeout, a
later retry with the same application idempotency key reaches the provider
with the *same* provider-level key, and the provider (or, for Stripe, its
own native `idempotency_key` parameter) returns the already-committed
result instead of duplicating the side effect. See
`integrations/tests/test_tools_payment.py::TestPaymentRefund::test_ambiguous_timeout_does_not_double_refund_on_manual_retry`
for the executable proof.

## Two-layer timeout

`integrations.services.effective_provider_timeout` bounds the provider's own
network timeout strictly below the remaining Phase 6 tool-execution
deadline (with a fixed margin), and below
`INTEGRATIONS_MAX_TIMEOUT_SECONDS`. Real adapters configure this as the
*SDK's own* socket/connection timeout (Stripe's `RequestsClient(timeout=…)`,
`httplib2.Http(timeout=…)` for Google, SMTP's `timeout=…`) — not only a
wrapping thread-pool timeout — so the inner I/O call normally terminates on
its own before Phase 6's outer `ThreadPoolExecutor` timeout would fire,
reducing (not eliminating — see the Phase 6 docs) orphaned external calls.

## RBAC

Connection management (`integrations.permissions.CanManageIntegrations`) is
owner/admin only — a support agent cannot submit or rotate Stripe/Calendar/
SMTP credentials. Read access (list/detail) is any active workspace member,
since the response is always secret-free. Business tool execution itself is
governed the same way every Phase 6 tool is: by `ToolBinding` on the agent
version, not by the calling human's role.

## Money representation

Amounts are always integer minor units (`amount_minor`), never floating
point — `payment.refund`'s `amount_minor` field is validated `> 0` and
checked against the fake/adapter's refundable balance before any provider
call. Currency is always normalized to uppercase ISO-4217.

## Phase 8 boundary

**`payment.refund` and `calendar.create_booking` do not implement business
authorization.** A successful call proves the execution mechanics work
(typed input, provider integration, idempotency, error normalization,
sandbox side effects) — it does not mean the action was *permitted*. Phase 8
adds the deterministic policy engine and human-approval gates that decide
whether a specific refund/booking should execute at all. Until then:

- Stripe only ever runs in test/sandbox mode — `INTEGRATIONS_LIVE_PROVIDERS_ENABLED`
  gates real adapters entirely, and no production Stripe key is used anywhere
  in this repository.
- There is no refund-threshold rule, role-based refund limit, or fake
  approval workflow anywhere in `integrations/`.

## Known limitations

- **Stripe refunded-amount tracking**: a bare `PaymentIntent` retrieve does
  not expose refunded amount without expanding `latest_charge`; Phase 7
  deliberately does not add that extra round-trip, so
  `payment.lookup`'s `refunded_amount_minor` is always `0` for the real
  Stripe adapter today (the fake provider tracks it correctly for tests).
  Full reconciliation is future work.
- **Google Calendar OAuth**: only a server-configured service-account
  credential is supported (section 135) — there is no per-user OAuth
  consent/redirect flow yet. Frontend-driven connection onboarding is a
  later phase.
- **CRM / n8n / webhook adapters**: explicitly out of scope for Phase 7
  (optional, and skipped in favor of quality on the required integrations).

## Testing

Default tests use the deterministic fakes exclusively — zero network, zero
paid API calls, zero real credentials. Real-adapter tests
(`test_stripe_provider.py`, `test_google_calendar_provider.py`,
`test_email_provider.py`) mock the adapter's *SDK boundary* only
(`stripe.StripeClient`, `googleapiclient.discovery.build`,
`django.core.mail.get_connection`), proving the vendor-behavior -> normalized
-domain-behavior mapping without touching a network.

Several tool-level tests use `@pytest.mark.django_db(transaction=True)`:
`execute_tool` dispatches the handler on a worker thread
(`concurrent.futures.ThreadPoolExecutor`), and a handler that queries the
database needs a *committed*, cross-connection-visible workspace — the
default `django_db` fixture's wrapping transaction is only visible on the
test's own connection. `integrations/tests/factories.bind_tool` uses
`get_or_create` rather than depending on the Phase 7 seed migration's rows
surviving a `TransactionTestCase`-style flush between tests.
