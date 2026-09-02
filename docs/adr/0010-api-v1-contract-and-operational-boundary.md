# ADR 0010: API v1 contract and operational boundary

## Status

Accepted (Phase 14 — API Contract, Documentation, and Operational
Hardening).

## Context

Phases 1-13 built the product API incrementally, domain by domain. By
Phase 14 the API surface was functionally complete but its cross-cutting
contract — versioning boundary, error shape, pagination, rate-limit
categories, and the operational endpoints' place relative to all of it —
had never been stated as a single decision. Client developers (Phase 18
frontend, and any future integrator) need one place that says what is
guaranteed to stay stable and what is explicitly not part of that
guarantee.

## Decision

1. **Versioning.** Every product/operator resource lives under
   `/api/v1/...`, including the public transport endpoints
   (`/api/v1/channels/public/...`) — they are unauthenticated by design,
   not unversioned. Operational endpoints (`/health/`, `/ready/`,
   `/metrics/`) are deliberately outside `/api/v1/` and outside this
   contract entirely: they are infrastructure surfaces with their own
   (often absent) auth model, not product API. No second versioning scheme
   (Accept-header negotiation, query-string version) exists or is planned
   without a new ADR.

2. **Stable error envelope.** Every handled API error is
   `{"error": {"code", "message", "details"?}}`. `code` is the stable,
   client-branchable contract; `message` is human-readable and may change
   wording without notice; `details` is optional structured context.
   Domain-specific codes beyond the small cross-cutting set
   (`validation_error`, `authentication_failed`, `permission_denied`,
   `not_found`, `conflict`, `rate_limited`, `service_unavailable`,
   `internal_server_error`) are documented next to the code that raises
   them, not centrally enumerated — see
   `docs/api/frontend-integration.md`.

3. **Shared pagination.** One pagination class
   (`common.pagination.StandardResultsSetPagination`, page-number,
   default 50 / max 500) for every list endpoint, with two named,
   documented exceptions (agent-run steps; web-chat message history) that
   are bounded by a domain-specific ceiling instead. No cursor-pagination
   endpoint exists in this codebase to preserve as an exception; if one is
   introduced later it must be justified and documented explicitly, not
   silently forced into page-number pagination or left undocumented.

4. **Rate-limit categories.** A small, fixed, server-controlled set of
   throttle scopes — `AUTH`, `PUBLIC_CHAT`, `PUBLIC_SIGNED_INGRESS`,
   `AGENT_EXECUTION`, `EVALUATION_EXECUTION`, `SENSITIVE_MUTATION` — rather
   than a bespoke throttle per endpoint or a single blanket
   `GENERAL_API` scope applied mechanically everywhere. `GENERAL_API` was
   evaluated and deliberately not implemented: ordinary reads/writes are
   already gated by authentication and workspace RBAC, and no concrete
   abuse risk justified adding uniform throttling across the whole API
   surface (Phase 14, Milestone 3).

5. **Breaking-change policy.** A breaking response/request shape change,
   or the removal/rename of an enum value or a stable error code, requires
   a new API version or an explicit migration plan — never a silent v1
   behavior change. Adding an optional response field is non-breaking.

## Consequences

- Client code can rely on the error/pagination/rate-limit shape being
  identical across every domain, reducing per-endpoint client-side
  special-casing.
- Operational tooling (health checks, metrics scrapers, load balancers)
  never needs product authentication, and product API changes never touch
  those paths.
- A future genuine v2 (or a cursor-paginated endpoint, or a new throttle
  category) is an explicit, documented decision — this ADR is the record
  future changes are measured against, not a wish list to expand
  informally.
- Public rate-limit identity (`PUBLIC_CHAT`, `PUBLIC_SIGNED_INGRESS`, and
  unauthenticated `AUTH`) is network-address-based. Milestone 4 flagged
  that this deployment's DRF configuration (`NUM_PROXIES` unset) trusted a
  client-supplied `X-Forwarded-For` header with no reverse proxy in front
  to strip it — a genuine, direct spoofing path. That gap was closed in a
  narrow follow-up remediation: DRF's `NUM_PROXIES` is now set explicitly
  via the `DRF_NUM_PROXIES` environment variable, defaulting to `0`
  (matches the current no-proxy topology — forwarded headers are never
  trusted, identity is always the direct peer address), with a positive
  value reserved for a deployment that genuinely sits behind that many
  trusted, header-sanitizing proxies. See
  `docs/api/frontend-integration.md`'s "Reverse proxy / client identity"
  section for the full contract. This is a correct default configuration,
  not a completed security audit — Phase 15's systematic spoofing/bypass
  campaign against the full API surface is still expected to run.
