# Frontend Integration Contract

Status: describes the **current** backend contract as of Phase 14. This is
documentation, not aspiration — every claim below is verified against the
actual settings, serializers, and tests in `backend/`. No frontend code has
been written yet (per the mandatory build order); this document exists so
Phase 18 frontend implementation can start from a correct contract instead
of reverse-engineering one.

## Base URL and versioning

- All product/operator APIs live under `/api/v1/...`.
- Public transport endpoints (web-chat, signed inbound webhooks) live under
  `/api/v1/channels/public/...` — versioned identically to the rest of the
  API, but unauthenticated by design (see [Channel / web-chat contract](#channel--web-chat-contract)).
- Operational endpoints — `/health/`, `/ready/`, `/metrics/` — are
  deliberately **unversioned** and sit outside `/api/v1/`. They are
  infrastructure surfaces, not product API; `/metrics/` additionally uses
  its own bearer-token scheme, entirely separate from product auth.
- There is no `Accept`-header or query-string version negotiation. `/api/v1/`
  is the only scheme in use.

## Authentication and CSRF lifecycle

The browser-facing auth flow uses a JSON access token plus an HttpOnly
refresh cookie — never a bare bearer token stored in JS-accessible storage
for the refresh credential.

1. **Prime CSRF** — `GET /api/v1/auth/csrf/` (no auth required). Sets the
   `sp_csrftoken` cookie. Call this once before `login`/`refresh`/`logout`.
2. **Login** — `POST /api/v1/auth/login/` with `{"email", "password"}` and
   header `X-CSRFToken: <sp_csrftoken cookie value>`.
   - `200`: `{"access": "<JWT>", "user": {"id", "email", "display_name", "workspaces": [{"id", "name", "slug", "role"}]}}`.
     The refresh token is **never** in this JSON body — it is set as an
     HttpOnly cookie on the response.
   - `401`: stable `authentication_failed` error (generic — never reveals
     whether the email exists).
   - Throttled at the `login` scope (Section on rate limits below).
3. **Access token** — sent by the client as `Authorization: Bearer <token>`
   on every subsequent request. Lifetime: 15 minutes.
4. **Refresh** — `POST /api/v1/auth/refresh/`, no body; the server reads the
   refresh token from its HttpOnly cookie (`sp_refresh_token`, path
   `/api/v1/auth/`). Also requires the `X-CSRFToken` header (cookie-based
   auth is CSRF-protected). Rotates the refresh token
   (`ROTATE_REFRESH_TOKENS=True`) and blacklists the previous one
   (`BLACKLIST_AFTER_ROTATION=True`); response is `{"access": "<new JWT>"}`
   plus a new refresh cookie. Refresh token lifetime: 7 days.
5. **Logout** — `POST /api/v1/auth/logout/` (CSRF header required).
   Blacklists the current refresh token and clears its cookie. Idempotent —
   a missing/already-invalid token still returns `204`.
6. **Current user** — `GET /api/v1/auth/me/` (bearer token required).
   Returns the same `user` shape as login, including every active
   workspace membership — the client never needs a separate
   "list my workspaces" call to build a workspace switcher.

**Refresh cookie attributes**: `HttpOnly`, `SameSite=Lax` (default,
env-configurable), `Secure` (forced true outside `DEBUG`), `Path=/api/v1/auth/`.

**CORS**: `CORS_ALLOW_CREDENTIALS=True`, origins restricted to an explicit
allowlist (`CORS_ALLOWED_ORIGINS`) — no wildcard. The frontend must issue
requests with `credentials: 'include'` for the refresh cookie to be sent.

## Workspace scoping

Every product resource route is nested under a workspace:
`/api/v1/workspaces/<uuid:workspace_id>/<resource>/...`. There is no
implicit "current workspace" on the server — the frontend must always
include the workspace id in the URL, sourced from the `workspaces` array on
the current-user response, never from a client-side guess.

A `workspace_id` for a workspace the caller is not an active member of
returns **404**, identically to a workspace that does not exist — this is
deliberate (Section on error contract) and must not be treated as a bug to
work around.

## Pagination

Every list endpoint (with two documented, deliberate exceptions below) uses
one shared page-number pagination contract:

```json
{ "count": 123, "next": "http://.../?page=3", "previous": "http://.../?page=1", "results": [...] }
```

- Default page size: **50**. Query param: `page_size` (up to a hard max of
  **500** — larger values are silently capped, never rejected). Page
  selector: `page`.
- A malformed `page`/`page_size` value falls back to DRF's default
  behavior (ignored, default page returned) rather than erroring.
- Ordering is always deterministic — every paginated queryset has an
  explicit tie-breaker (see [Filtering and ordering](#filtering-and-ordering)),
  so identical timestamps never produce a flaky/duplicated page.

**Deliberate exceptions** (do not build pagination UI for these as if they
were standard lists):
- **Agent run steps** (`GET .../agent-runs/<id>/steps/`) — bounded by
  `AgentVersion.max_steps` (≤200), not paginated.
- **Web-chat message history** (public, session-scoped poll) — capped at
  `CHANNEL_WEBCHAT_MESSAGE_HISTORY_LIMIT` (default 200) per call; the
  widget polls incrementally via the `after` cursor rather than paging.

## Filtering and ordering

Filters are explicit, named query parameters per endpoint — never arbitrary
ORM-style lookups (`?field__contains=...` is not supported anywhere).
Representative examples: `status`, `channel`, `customer`, `assigned_to`,
`conversation`, `priority`, `dataset_id`, `agent_id`, `agent_run_id`,
`source_id`.

A malformed UUID-shaped filter value (e.g. `?customer=not-a-uuid`) returns
the stable `400 validation_error` envelope — it is never silently ignored
and never crashes as a raw 500. A client should treat this exactly like any
other field validation error.

There is no generic client-facing `ordering=` parameter across the board;
where ordering is exposed it is a small bounded set of named fields, never
an arbitrary model field, and the default order is always deterministic.

## Error contract

Every handled API error uses one stable envelope:

```json
{ "error": { "code": "validation_error", "message": "Human-readable message.", "details": { } } }
```

`details` is optional and present only for structured contexts (field-level
validation errors, a bounded `retry_after` on `rate_limited`).

Stable, cross-cutting codes a client should branch on:

| Code | HTTP status | Meaning |
|---|---|---|
| `validation_error` | 400 | Malformed request body or filter |
| `authentication_failed` | 401 | Missing/invalid/expired credentials |
| `permission_denied` | 403 | Authenticated, but not authorized for this action |
| `not_found` | 404 | Resource does not exist, or exists in another workspace (identical response) |
| `conflict` | 409 | Request conflicts with current state (also many domain-specific 409 codes, below) |
| `rate_limited` | 429 | Throttled — see [Rate limits](#rate-limits) |
| `service_unavailable` | 503 | The shared throttle cache is unreachable (Section 19-24 below) |
| `internal_server_error` | 500 | Unhandled server error — no raw exception ever reaches this body |

Beyond these, many domain actions raise their **own** stable, documented
code at 400/403/404/409 (e.g. `agent_version_not_published`,
`webhook_destination_blocked`, `approval_already_resolved`,
`integration_disabled`, `knowledge_malformed_pdf`). Treat every code the
API actually returns as part of the contract, but do not assume every
future domain code is permanent — see
[Deprecation policy](#deprecation-policy).

A raw Python exception, ORM error, or provider SDK error is never surfaced
in a response body under any circumstance covered by the test suite.

## Rate limits

| Category | Applies to | Identity |
|---|---|---|
| `AUTH` | login, refresh | Authenticated user id if known, else network address |
| `PUBLIC_CHAT` | web-chat session bootstrap + message submit/poll | Network address (unauthenticated by design) |
| `PUBLIC_SIGNED_INGRESS` | signed provider webhook | Network address (signature is the real auth boundary; this is defense-in-depth) |
| `AGENT_EXECUTION` | agent run creation only (not listing) | Authenticated user id |
| `EVALUATION_EXECUTION` | evaluation run creation + result replay (not listing) | Authenticated user id |
| `SENSITIVE_MUTATION` | integration/webhook/channel credential rotation | Authenticated user id |

A throttled request returns `429` with `error.code = "rate_limited"` and,
when available, `error.details.retry_after` — a bounded integer number of
seconds. Never treat its absence as an error; not every throttle backend
call supplies it.

**Cache-outage behavior**: if the shared Redis-backed throttle cache itself
is unreachable, every one of the categories above fails **closed** with
`503 service_unavailable` — never a raw 500, and never silently treated as
"unlimited" traffic. A client should treat `503` here as "try again
shortly", distinct from `429`'s "you are over quota".

**Network-identity caveat (read before deploying behind a proxy)**: see
[Reverse proxy / client identity](#reverse-proxy--client-identity-read-this-before-production) —
this is a known, currently-open configuration gap, not a documented
guarantee.

## Request / correlation IDs

- A client may send `X-Request-ID` on any request. It is validated against
  a bounded, ASCII-safe pattern (`^[A-Za-z0-9._-]{1,128}$`); an
  invalid/missing value is silently replaced with a fresh server-generated
  UUID4 — the request is never rejected for a malformed id.
- The (possibly server-replaced) id is always echoed back on the response
  as `X-Request-ID`. Use it to correlate a support ticket with server-side
  logs/traces.
- Request IDs are never used as Prometheus metric labels (unbounded
  cardinality) and never logged raw as anything but the correlation id
  itself.

## Timestamps

Every timestamp field is timezone-aware and serializes as ISO-8601
(`USE_TZ=True`, DRF's default `iso-8601` renderer — no custom format
override anywhere in the codebase). Values are stored in UTC and rendered
with a `Z`/`+00:00` suffix; do not assume a naive/local timestamp anywhere.

## Money / decimal representation

Two distinct patterns exist — do not conflate them:

- **Business monetary amounts** (order/payment/refund amounts moved
  through tools and integrations) are always an **integer minor-unit
  amount** (`amount_minor`, e.g. cents) plus a separate `currency` string
  (ISO 4217-shaped, e.g. `"USD"`). There is no floating-point money
  anywhere in this path.
- **Cost-estimate fields** (`AgentRun.estimated_cost_usd`,
  `AgentVersion.max_estimated_cost_usd`) are Django `DecimalField`s and, per
  DRF's default `COERCE_DECIMAL_TO_STRING=True` (not overridden here),
  serialize as **JSON strings** (e.g. `"0.0421"`), never as a JSON number —
  parse them as decimals client-side, not floats.

## Agent run lifecycle

Actual `AgentRun.status` values (no others exist):
`pending`, `running`, `succeeded`, `failed`, `cancelled`,
`budget_exceeded`, `waiting_for_approval`, `handed_off`.

- A run is created via `POST .../agent-runs/` (throttled, `AGENT_EXECUTION`)
  and begins `pending`, then `running`.
- `waiting_for_approval`: a bound tool call requires a human decision. The
  associated `ApprovalRequest` is reachable via the approvals endpoints
  (below); deciding it resumes the **same persisted run** — the frontend
  should poll the run, not assume a new run id appears after approval.
- `handed_off`: the run created a `HumanHandoff` and stopped autonomously;
  poll the handoff/ticket, not the run, for what happens next.
- `budget_exceeded`: a bounded resource ceiling (model calls, tool calls,
  wall time, token/cost budget) was hit — a safe, deterministic stop, not a
  crash.
- `cancelled`: explicitly cancelled via the cancel endpoint.
- Terminal states are `succeeded`, `failed`, `cancelled`, `budget_exceeded`,
  and `handed_off` — a run does not transition further out of these.

There is no server-sent-event/WebSocket push for run status today — the
frontend must poll `GET .../agent-runs/<id>/` (unthrottled) until a
terminal or `waiting_for_approval`/`handed_off` status.

## Approval lifecycle

Actual `ApprovalRequest.status` values: `pending`, `approved`, `rejected`,
`expired`, `cancelled`. A decision is `POST` with `{"decision": "approve"|"reject"}`
plus an optional comment.

- Repeated identical decisions are idempotent (replaying the same decision
  on an already-resolved request returns the existing resolved row, `200`).
- A *conflicting* decision on an already-resolved request is `409` with
  `error.code = "approval_already_resolved"`.
- A stale pending request transitions to `expired` on its own (TTL-based) —
  the frontend should treat `expired` as terminal, not retry the decision.
- Approving resumes the originating `AgentRun` from its persisted state —
  the frontend does not need to re-trigger anything itself.

## Evaluation flow

- `POST .../evaluations/runs/` starts a run against a dataset's active
  cases (published agent version required); each case executes to a
  terminal `EvaluationResult` (`succeeded`/`failed`/`cancelled`), and the
  run itself auto-finalizes to `succeeded`/`partial`/`failed` as soon as
  every case completes — the frontend does not call a separate "finalize"
  endpoint.
- Results are listed at `.../runs/<id>/results/` (standard pagination).
- `.../runs/<id>/results/<result_id>/replay/` re-executes one case
  (throttled, `EVALUATION_EXECUTION`).
- `.../runs/compare/` compares two runs.
- Ordinary evaluation runs use the repository's deterministic offline
  provider and require **no paid API** — this is true in every environment
  including CI. A real-model evaluation run is a separate, explicitly
  opt-in configuration, out of scope for normal frontend development.

## Channel / web-chat contract

Public, unauthenticated-by-design endpoints under
`/api/v1/channels/public/...` — the schema correctly declares no
JWT/cookie security requirement on any of them:

1. `POST .../webchat/<endpoint_id>/session/` — bootstraps an anonymous
   session. Returns `{"session_token", "expires_at"}`. The token is a
   one-time capability value: it is the caller's only credential for every
   subsequent call on this session and is never re-issued or logged
   server-side.
2. `POST .../webchat/session/<session_token>/messages/` — submit a
   customer message. `{"client_message_id", "body"}`; `client_message_id`
   is the caller's own idempotency key — resubmitting the same id with the
   same body is an idempotent `202` accept (same `message_id` both times);
   the same id with a *different* body is an `idempotency_conflict`. This
   is an async-accept contract: `202`, not `200` — the agent's reply
   arrives via the message-history poll below, not in this response.
3. `GET .../webchat/session/<session_token>/messages/?after=<message_id>` —
   poll for new messages. `after` is an opaque cursor (not a timestamp);
   omit it only for the first call. Capped at
   `CHANNEL_WEBCHAT_MESSAGE_HISTORY_LIMIT` per call (see
   [Pagination](#pagination)).
4. `POST .../inbound/<endpoint_id>/` — the **signed provider webhook**
   path (generic/email-style channels), never called by a browser client.
   Authenticated by an HMAC signature header plus a bounded
   timestamp-freshness window, entirely independent of session tokens or
   staff auth. A byte-identical redelivery of an already-processed event is
   an idempotent `202` accept (Section on delivery guarantees below), never
   an error — the frontend has no reason to call this endpoint directly.

The signing secret for the inbound webhook path is never exposed by any
read endpoint after its one-time creation/rotation response.

## Deprecation policy

Minimal v1 policy, current as of this document:

- A breaking response/request shape change requires a new API version or
  an explicit, documented migration — never a silent v1 behavior change.
- Adding a new **optional** response field is non-breaking.
- Removing or renaming an enum value, or a stable error code, is breaking.
- Any other behavior change (throttle rate, pagination default, etc.) gets
  documented here before it ships, not discovered by the frontend in
  production.

## Reverse proxy / client identity (read this before production)

**This is an open configuration gap, not a guarantee** — see the Phase 14
Milestone 4 report for the full writeup. Summary: `PUBLIC_CHAT` and
`PUBLIC_SIGNED_INGRESS` rate-limit identity is "network address as DRF's
`ScopedRateThrottle` determines it", and DRF's default `NUM_PROXIES=None`
(unmodified in this repository) makes it **trust a client-supplied
`X-Forwarded-For` header whenever one is present** — with no reverse proxy
in the current deployment topology to strip or overwrite it. A caller can
today set their own `X-Forwarded-For` value per request to obtain a fresh
rate-limit identity on demand. Do not build frontend logic that assumes
this rate limiting is currently spoof-resistant; systematic testing and a
fix are explicitly Phase 15 scope, not resolved here.
