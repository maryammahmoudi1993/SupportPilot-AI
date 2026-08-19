# ADR 0005: Provider-Independent Business Integrations Behind the Typed Tool Boundary

- Status: Accepted
- Date: 2026-08-19

## Context

Phase 6 built the trusted execution boundary — registry, typed contracts,
idempotency, timeouts, redaction — but the only tools registered were
deterministic, side-effect-free demos. Phase 7 has to prove that boundary
survives contact with real, side-effecting external systems (payments,
calendars, notifications) without the two failure modes that boundary was
built to prevent: a vendor SDK leaking into agent-reachable code, and a
second, weaker execution path growing up alongside the trusted one because
"the provider SDK makes direct calls convenient." A second, related risk is
premature: Phase 7 has no policy/approval engine yet, so a refund or booking
tool that *looks* authorization-aware without a real policy behind it would
be worse than one that is honest about proving mechanics only.

## Decision

1. **Business tools are ordinary `tools.contracts.Tool` registrations, not a
   new kind of thing.** `integrations.apps.IntegrationsConfig.ready()`
   registers `customer.lookup`, `order.lookup`, `shipment.lookup`,
   `payment.lookup`, `payment.refund`, `calendar.check_availability`,
   `calendar.create_booking`, `ticket.create`, `ticket.update`, and
   `notification.send` into the *same* `tools.registry` the Phase 6 demo
   tools use, and they run through the *same*, unmodified
   `tools.execution.execute_tool`. There is no
   `integrations.execution.execute_business_tool` — extending the platform
   to a real integration required zero changes to the execution service.
2. **Every vendor sits behind a project-owned typed protocol
   (`integrations/providers/base.py`), never called directly from a tool
   handler.** A handler calls `integrations.services.<operation>`, which
   resolves the workspace's `IntegrationConnection`, decrypts credentials
   immediately before use, and calls a `PaymentProvider` /
   `CalendarProvider` / `NotificationProvider` / `OrderProvider` instance
   resolved by `integrations.providers.factory`. No `stripe.*`,
   `googleapiclient.*`, or `smtplib.*` type is importable from `tools.py`.
3. **Fake-by-default, live-opt-in, at the factory, not per test.**
   `INTEGRATIONS_LIVE_PROVIDERS_ENABLED` (default `False`) is the only
   switch between `providers.fakes.*` and a real adapter
   (`stripe_provider`, `google_calendar`, `email_provider`); the default
   test suite, CI, and local dev all get the deterministic fakes without
   any test needing to know that. `demo_commerce.DemoCommerceProvider` is
   the sole `OrderProvider` — there is no live commerce vendor to gate, so
   pretending one exists (a "fake commerce adapter" wrapping a nonexistent
   real one) was rejected as needless indirection.
4. **A refund/booking tool proves execution mechanics, not authorization.**
   `payment.refund` and `calendar.create_booking` have no threshold rule,
   role-based limit, or approval check anywhere in `integrations/` — Phase 8
   owns that decision entirely. Their `ToolSpec.description` says this
   explicitly, and the module docstrings repeat it, so a future reader
   (human or agent) cannot mistake "this tool runs successfully in test
   mode" for "this action is authorized in production."
5. **Provider-level idempotency key = `f"{tool_key}:{context.tool_execution_id}"`.**
   No new idempotency-mapping table. Phase 6 already guarantees
   `tool_execution_id` is stable across every retry of one logical
   ToolExecution row (same key resets the same row to `PENDING`), so
   deriving the provider key from it for free reuses that guarantee instead
   of building a second one. This is also what makes the "ambiguous
   timeout" case (provider committed, client saw a timeout) safe on a
   caller-initiated retry: the retry reaches the provider with the exact
   same key.
6. **Credentials are encrypted with `cryptography.fernet`, decrypted only
   inside `integrations.services._execute_provider_call`.** Rejected:
   hand-rolled AES-GCM (reinventing a solved problem the CLAUDE.md rules
   explicitly warn against); storing credentials in `ToolBinding.configuration`
   (mixes secrets into a JSON field several other layers already read/log);
   decrypting once at connection-load time and passing plaintext around
   (widens the plaintext-lifetime window across function boundaries for no
   benefit).
7. **Real adapters set the provider SDK's own network timeout, not only a
   wrapping thread timeout.** `effective_provider_timeout` bounds it
   strictly under the remaining Phase 6 deadline. This directly addresses
   Phase 6's documented "a timed-out handler may keep running in the
   background" limitation for the specific, common case of an I/O-bound
   external call — it does not remove the limitation (Python still cannot
   forcibly kill the worker thread), but it meaningfully reduces how often
   it's hit.
8. **`IntegrationConnection` is one-per-`(workspace, provider)`, DB-enforced.**
   Simpler than a "default connection" pointer or admin-configured binding
   indirection, and it removes an entire class of "which connection did the
   model mean" ambiguity at the schema level — a business tool never
   receives or needs a connection identifier.

## Alternatives rejected

- **A generic "call any provider method" tool** parameterized by
  provider/operation/params — rejected outright; it is the same SSRF/
  arbitrary-execution shape ADR 0004 already rejected for HTTP, just at the
  provider layer instead of the network layer.
- **Storing plaintext credentials and relying on network/DB access control**
  — rejected; CLAUDE.md requires encrypted-at-rest secrets, and access
  control alone doesn't survive a database backup leak or an internal
  overprivileged query.
- **A lightweight in-repo "policy stub" for refunds** (e.g. a hardcoded
  amount ceiling) to make the refund tool feel safer today — rejected; it
  would be a fake approval system exactly like CLAUDE.md prohibits, and it
  would need to be torn out (not extended) once Phase 8's real policy engine
  exists.
- **Multiple `IntegrationConnection` rows per provider with model-selectable
  IDs** — rejected; every extra degree of freedom here is an extra thing an
  agent-controlled argument could misuse (section 108's connection-spoof
  concern), for no capability this phase actually needs.

## Consequences

Benefits:

- Phase 8's policy/approval engine can wrap `payment.refund` and
  `calendar.create_booking` without touching `integrations/` internals — the
  tools already produce a clean, typed, idempotent unit of work; policy only
  needs to decide whether to call `execute_tool` at all (or pause for
  approval first).
- adding a second payment/calendar/notification vendor later is "implement
  the `Protocol`, register it in the factory" — no change to
  `integrations.tools` or `integrations.services`.
- the ambiguous-timeout / duplicate-refund guarantee is regression-tested
  end-to-end (`test_ambiguous_timeout_does_not_double_refund_on_manual_retry`),
  not just asserted in a docstring.

Trade-offs:

- `payment.lookup`'s `refunded_amount_minor` is `0` for the real Stripe
  adapter (a bare `PaymentIntent` retrieve doesn't expose it without an
  extra expand round-trip) — a known, documented limitation rather than a
  silently wrong value.
- Google Calendar only supports a server-configured service-account
  credential; there is no per-user OAuth consent flow, so a workspace admin
  configures one shared calendar identity rather than each agent acting as
  a specific human's calendar.
- one connection per `(workspace, provider)` means a workspace that
  genuinely needs two Stripe accounts cannot express that yet — an
  intentional simplicity-over-flexibility choice for this phase, matching
  ADR 0004's bias.
