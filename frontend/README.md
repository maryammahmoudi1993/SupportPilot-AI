# SupportPilot AI — Frontend

The frontend for SupportPilot AI: a Next.js (App Router) application that
consumes the Django/DRF backend in [`../backend`](../backend). This is
**Phase 18** — through Chunk 2, that's framework, design system, typed API
transport, and authentication. Workspace context, protected routing beyond
a single placeholder route, and the real application shell land in the
following chunks; see
[`../SupportPilot_AI_Master_Build_Prompt.md`](../SupportPilot_AI_Master_Build_Prompt.md).

## Stack

| Concern              | Choice                                               |
| -------------------- | ---------------------------------------------------- |
| Framework            | Next.js 16 (App Router, Turbopack)                   |
| Language             | TypeScript, `strict: true`                           |
| UI runtime           | React 19                                             |
| Styling              | Tailwind CSS v4 (CSS-first `@theme` tokens)          |
| API contract         | drf-spectacular OpenAPI → `openapi-typescript`       |
| API transport        | `openapi-fetch`, wrapped in `src/lib/api`            |
| Unit/component tests | Vitest + React Testing Library                       |
| Formatting/linting   | Prettier, ESLint (flat config, `eslint-config-next`) |

No state-management or server-state library (Redux, Zustand, TanStack
Query, ...) has been introduced. Auth state is one small, mostly-singleton
tree — a React context (`AuthProvider`) is enough, and none of Chunk 2's
data fetching (login/logout/me) benefits from a caching layer built for
lists of server records. Revisit for workspace/business data in a later
chunk, per the "don't add a layer for fashion" principle in the build
prompt. `msw` was added, but only as a dev dependency for tests.

## Directory structure

```
frontend/
  src/
    app/            App Router routes, layouts, and route-level UI states
    components/ui/  Design-system primitives (Button, Input, Card, ...)
    features/
      auth/          Login/logout/me operations, AuthProvider, LoginForm, redirect safety
    lib/            Framework-agnostic code: API transport, config, utils
      api/           Central HTTP client, token/session/CSRF handling, error normalization
    types/          Generated types only (api.ts) — never hand-edited
    tests/          Vitest specs, mirroring the src/ layout they cover
      msw/           Request-level mocks for the auth endpoints
  scripts/          Node scripts (API type generation, drift check)
  openapi.yaml      Generated OpenAPI schema snapshot (see below)
```

Other feature domains (customers, conversations, tickets, agents,
approvals, knowledge, integrations, evaluations, settings) get their own
directories under `src/features/` starting in the phase that implements
them — `auth` is the first, and the pattern it establishes (a feature owns
its API calls, its own React state, and its own tests; transport-level
concerns generic across features stay in `lib/api`) is meant to repeat.

## API contract and type generation

The backend is the source of truth. `src/types/api.ts` is generated from the
backend's live OpenAPI schema (via `drf-spectacular`) and must never be
hand-edited — every request path, method, query/body shape, and response
shape it describes is checked against the real backend at compile time.

To regenerate both the schema snapshot (`openapi.yaml`) and the types
(`src/types/api.ts`) from a local backend checkout:

```bash
npm run generate:api-types
```

This requires a backend virtualenv at `../backend/venv` (see the
"Quick Start" section of `../README.md` for setup) but does **not** require a running server,
database, or Redis instance — it builds the schema by importing the Django
app configuration directly, using `--fail-on-warn` so a schema regression
fails loudly instead of silently drifting.

Run it whenever the backend's API surface changes, and commit the
regenerated `openapi.yaml` + `src/types/api.ts` together with the frontend
change that needed them, so the frontend build never silently depends on an
undocumented response shape.

To check whether the committed files are stale (e.g. in CI, or before a
release) without touching them:

```bash
npm run check:api-types
```

This regenerates into a throwaway temp directory, diffs against the
committed `openapi.yaml`/`src/types/api.ts`, and exits non-zero on any
difference — the working tree is never written to.

**Known schema gaps** (real backend-side gaps, not papered over with `any`
on the frontend — see `src/lib/api/session.ts` and
`src/features/auth/types.ts`):

- `POST /api/v1/auth/refresh/`'s 200 response is documented via
  `OpenApiResponse(description=...)` rather than a response serializer, so
  drf-spectacular emits `content?: never` for it even though the view really
  returns `{ access: string }`. `session.ts` defines a small
  `RefreshResponseBody` interface documenting exactly that gap, with an
  explicit, commented cast — not a blanket `any`.
- `Me.workspaces` (the current-user endpoint's workspace-membership summary)
  is a `SerializerMethodField` drf-spectacular can't resolve, so it's typed
  as `{ [key: string]: unknown }[]`. Chunk 2 doesn't read this field (no
  workspace UI yet); Chunk 3 (workspace context) should either add
  `@extend_schema_field` on the backend serializer or, if that's not
  practical, define a small typed interface matching the real
  `WorkspaceMembershipSummarySerializer` output the same way `session.ts`
  does above.

Neither gap was worked around by changing backend code in Phase 18 — see
"Backend contract" below.

## API transport (`src/lib/api`)

- **`client.ts`** — the one `apiClient` instance (`openapi-fetch`, typed
  against `src/types/api.ts`), bound to `NEXT_PUBLIC_API_BASE_URL` (an
  **origin only** — the generated paths are already absolute, e.g.
  `/api/v1/auth/login/`; a base URL that itself included `/api/v1` would
  double it — see `src/tests/lib/api/client.test.ts`), with
  `credentials: "include"` so the backend's cookies are sent automatically.
  `fetch` is resolved dynamically per call (`(...args) => globalThis.fetch(...args)`)
  rather than captured once at client-creation time — required for MSW to
  intercept requests in tests, and generally more robust. Registers two
  request middlewares (Authorization, CSRF — see "Authentication" below). No
  feature code should construct its own `fetch()`/client.
- **`errors.ts`** — normalizes the backend's real error envelope
  (`{ "error": { "code", "message", "details"? } }`, see
  `backend/common/exceptions.py`) plus network/timeout/parse failures into
  one typed `ApiError`, so UI code branches on `error.code` rather than
  parsing raw responses.
- **`timeout.ts` / `request.ts`** — `withRequestTimeout` applies a default
  15s timeout (`DEFAULT_TIMEOUT_MS`) to a request, combinable with a
  caller-supplied `AbortSignal` (e.g. component unmount); `unwrap` converts
  an `openapi-fetch` `{ data, error, response }` result into throw-on-failure
  form. Long-running or upload endpoints should pass their own timeout
  rather than inherit the default.
- **`token-store.ts` / `csrf.ts` / `session.ts` / `topology.ts` /
  `logout-intent.ts`** — see "Authentication" below.

## Design system

**Light theme only, by intentional decision** — a calm, high-trust B2B
operations surface. A dark-mode toggle was not added: half-implemented
theming would be worse than a deliberately single, high-quality theme for
this phase's scope. Revisit if a later phase has an actual product reason
to support dark mode.

Tokens live in `src/app/globals.css` as Tailwind v4 CSS-first `@theme`
variables (surface/border/text scales, a single primary accent, semantic
status colors, radius scale, and shell layout constants) — feature code
should reference the generated utilities (`bg-surface-2`,
`text-text-secondary`, `border-border-default`, ...) rather than hardcoding
colors. `:focus-visible` gets a consistent, always-visible outline; it is
never suppressed without a replacement.

Primitives in `src/components/ui/` (Button, Input, Label, Card, Badge,
Alert, Spinner, Skeleton, Separator) are hand-built on native HTML elements
rather than a component library — nothing built so far needs compound
accessibility behavior (a menu, a dialog) that would justify pulling in
Radix. That's the natural point to introduce it, when the app shell
(Chunk 3) needs a workspace switcher / user menu.

## Environment variables

Copy `.env.example` to `.env.local` for local development:

```bash
cp .env.example .env.local
```

| Variable                   | Required | Notes                                                                                                                                                                                                                                                                                                                      |
| -------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_BASE_URL` | Yes      | Backend **origin only** (no `/api/v1` suffix — see "API transport" above), e.g. `http://localhost:8000`. Must share the browser's hostname (see "Cookie semantics" in "Authentication") — a runtime guard throws a clear error if it doesn't. Read and validated (fails fast if missing/malformed) in `src/lib/config.ts`. |

Every variable exposed to the browser is prefixed `NEXT_PUBLIC_`; nothing
else is read from `process.env` in client code. No backend secret is ever
read by, or exposed through, the frontend.

## Authentication

Backend contract (`backend/accounts/views.py`, `serializers.py`,
`services.py`; `backend/common/csrf.py`; `backend/config/settings.py`
`SIMPLE_JWT`/`AUTH_REFRESH_COOKIE_*`/`CSRF_*`) — inspected directly, not
assumed:

| Operation    | Method / path                | Auth                                   | CSRF required     |
| ------------ | ---------------------------- | -------------------------------------- | ----------------- |
| CSRF prime   | `GET /api/v1/auth/csrf/`     | none                                   | n/a (safe method) |
| Login        | `POST /api/v1/auth/login/`   | none                                   | yes               |
| Refresh      | `POST /api/v1/auth/refresh/` | refresh cookie                         | yes               |
| Logout       | `POST /api/v1/auth/logout/`  | refresh cookie (optional — idempotent) | yes               |
| Current user | `GET /api/v1/auth/me/`       | `Authorization: Bearer <access>`       | no (safe method)  |

**Credentials:**

- **Access token** — a short-lived (15 min) JWT returned in the JSON body of
  login/refresh. Held **in memory only**
  (`src/lib/api/token-store.ts`) — never `localStorage`, `sessionStorage`,
  or a frontend-set cookie. It does not survive a page reload by design;
  see "Session bootstrap" below for how a reload re-establishes it.
- **Refresh token** — a long-lived (7 days), rotated-on-every-use JWT set as
  an **HttpOnly** cookie (`sp_refresh_token`, path-scoped to
  `/api/v1/auth/`) directly by the backend
  (`accounts/services.py:set_refresh_cookie`). Frontend code never reads,
  writes, or even sees this cookie's value — it's invisible to JavaScript
  by design, and `apiClient`'s `credentials: "include"` is what makes the
  browser attach it automatically.
- **CSRF token** — Django's standard double-submit cookie
  (`sp_csrftoken`, JS-readable — that's inherent to the double-submit
  pattern, not a frontend choice). `src/lib/api/csrf.ts`'s
  `ensureCsrfCookie()` primes it via `GET /auth/csrf/` if not already
  present, before every login/refresh/logout call; `client.ts`'s request
  middleware then attaches it as the `X-CSRFToken` header on every
  non-safe-method request.

**Why login/refresh/logout need CSRF but nothing else does**: they
authenticate via the refresh cookie (or, for login, no prior auth at all),
which the browser attaches automatically to any request — including one
forged by another site. DRF's automatic CSRF exemption only covers its own
`SessionAuthentication`; these views authenticate a different way, so the
backend calls `enforce_csrf()` explicitly (see `backend/common/csrf.py`'s
own doc comment). `GET /auth/me/` doesn't need it: it's a safe method, and
it authenticates via the `Authorization` header, which — unlike a cookie —
a forged cross-site request can't attach on the victim's behalf.

### Session bootstrap and reload

There is deliberately no separate "try refresh, then fetch /me/" bootstrap
sequence. `AuthProvider` (`src/features/auth/auth-provider.tsx`) just calls
`fetchCurrentUser()` on mount; that goes through
`withAccessTokenRetry` (`src/lib/api/session.ts`), which is the _same_
401 → refresh → retry mechanism any protected call uses (see below). On a
fresh page load there is no in-memory access token, so the first call
naturally 401s, triggers a refresh via the HttpOnly cookie, and retries —
succeeding if a valid refresh cookie survived the reload, failing (cleanly,
to `unauthenticated`) if it didn't or has expired. One mechanism, not two.

`AuthState.status` is `"loading" | "authenticated" | "unauthenticated"` —
never inferred from `user === null` alone, so "haven't checked yet" and
"checked, not logged in" can't be confused (a protected page must never
flash its content, or redirect to `/login`, before bootstrap resolves).
`AuthState.error` additionally carries the `ApiError` when bootstrap failed
specifically because the network was unreachable (`network_error`/`timeout`)
rather than because the session was proven invalid
(`authentication_failed`) — `status` is still `"unauthenticated"` either
way (never claim authenticated without proof), but a caller can use `error`
to offer "Retry" instead of routing straight to the login form.

### Coordinated refresh (`src/lib/api/session.ts`)

`ensureFreshAccessToken()` is a mutex: while a refresh is in flight, every
concurrent caller awaits the _same_ promise instead of starting its own —
this is what makes "10 parallel requests get a 401" result in exactly one
`POST /auth/refresh/` call, not ten (see
`src/tests/lib/api/session.test.ts`'s parallel-401 test).
`withAccessTokenRetry(callFactory)` wraps a protected call: on a 401 it
refreshes once and calls `callFactory()` again from scratch (never a reused
`Request`/body, so this is safe even for a write, as long as the _first_
attempt never reached business logic — which a 401 guarantees, since
`JWTAuthentication` rejects before the view runs) — never a second retry,
and never a loop. If refresh itself fails, `withAccessTokenRetry` throws
the _refresh's_ error (not the original request's 401), which is what
preserves the network-vs-invalid-session distinction end to end.

Login, refresh, and logout themselves (`src/features/auth/api.ts`) call
`apiClient` directly and a plain `unwrap()` — never `withAccessTokenRetry`.
That's a structural guarantee, not a URL-based exclusion list: there is no
code path by which the refresh flow can recurse into itself.

A failed refresh (from _any_ caller, not just bootstrap) clears the
in-memory access token and calls `notifySessionExpired()`
(`token-store.ts`), which `AuthProvider` has registered a handler for —
one owner for "the session just ended" — but only acts if the app was
actually `"authenticated"` at that moment, so it can't clobber an
in-flight _first_ bootstrap that's about to commit its own (more specific)
unauthenticated/error state.

### Logout

`logout()` (`src/features/auth/api.ts`) clears the in-memory access token
as its very first statement — before the network call even starts — so
privileged UI disappears immediately regardless of what happens next. It
does **not** claim the server session is definitely gone: `logout()`
returns `"complete"` only if `POST /auth/logout/` actually succeeded, or
`"server_unconfirmed"` if that request failed (network outage, CSRF
hiccup, server error, ...). **The frontend never states "you are signed
out" as an unqualified fact when the server call failed** — the refresh
cookie may still be valid server-side until it naturally expires (7 days)
or a later attempt succeeds.

On `"server_unconfirmed"`, a non-secret boolean marker
(`src/lib/api/logout-intent.ts`, `localStorage["sp_logout_pending"]` — a
flag, never a credential) is set. `AuthProvider`'s `logoutPending` field
surfaces it, and the login page shows an explicit "sign-out not fully
confirmed" notice rather than silently pretending the session ended. The
marker also changes what the _next_ bootstrap does: instead of going
straight to `fetchCurrentUser()` (which would happily re-authenticate
using the still-technically-valid refresh cookie), `AuthProvider` retries
`logout()` first. Only once that retry actually succeeds does bootstrap
fall through to the normal authenticated/unauthenticated check — a reload
can never silently undo a logout the user asked for, even if the first
attempt's network call failed. The marker clears on that later success,
or immediately if the user chooses to log back in instead (a fresh login
supersedes the old session it replaces).

`localStorage` (not `sessionStorage`) was chosen deliberately: the
marker's entire purpose is to survive a reload and be visible to other
tabs, which is exactly what `sessionStorage`'s per-tab scoping would
defeat. No `storage` event listener was added for live cross-tab
push — each tab re-checks the marker at its own next bootstrap, which
closes the actual gap (reload silently re-authenticating) without the
complexity of real-time synchronization.

### Redirect safety

`src/features/auth/redirect.ts`'s `isSafeRedirectTarget`/`resolveRedirectTarget`
validate the login page's `?next=` param: only a root-relative path
(`/foo`) is accepted — an absolute URL, a protocol-relative URL (`//evil`),
a backslash variant some browsers normalize to one (`/\evil`), or any
target containing whitespace/control characters is rejected in favor of the
default (`/`). See `src/tests/features/auth/redirect.test.ts`.

### Cookie semantics

Three different things get conflated in casual discussion of cookies, and
this codebase must not conflate them either — each governs something
different, and only one of them actually matters for this frontend's CSRF
design:

| Term                  | Governs                                                        | Scope                                                                                                         |
| --------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| **Origin**            | Which requests count as "cross-origin" for CORS                | scheme + host + port                                                                                          |
| **Site** (`SameSite`) | Whether the browser **sends** a cookie on a given request      | registrable domain (eTLD+1), ignoring scheme/port                                                             |
| **Cookie `Domain`**   | Whether **JavaScript can read** a cookie via `document.cookie` | exact hostname match, unless the cookie explicitly sets a shared parent `Domain` (e.g. `Domain=.example.com`) |

This frontend's CSRF flow needs the **third** one: `client.ts`'s request
middleware reads the `sp_csrftoken` cookie's value out of `document.cookie`
to send as the `X-CSRFToken` header (see "Authentication" above). The
backend sets that cookie with **no explicit `CSRF_COOKIE_DOMAIN`**
(confirmed directly in `backend/config/settings.py` — grepped, not
assumed), making it a **host-only** cookie, readable only by JavaScript
running on the exact host that received it. The refresh cookie is the
same way (no `Domain` in `accounts/services.py:set_refresh_cookie`) —
though since the frontend never reads it, only "site" (for `SameSite`)
matters for that one, not hostname.

**Consequence**: an `app.example.com` frontend calling an
`api.example.com` backend is same-_site_ (fine for `SameSite=Lax` cookie
_sending_) but a **different hostname** — frontend JavaScript on
`app.example.com` cannot read a cookie `api.example.com` set with no
`Domain`. An earlier draft of this document called sibling subdomains
sufficient for production; that was wrong, conflating "same site" with
"cookie readable here", and has been corrected below.
`localhost:3000`/`localhost:8000` work in local dev for an unrelated
reason: cookie scoping ignores port entirely, and both share the literal
hostname `localhost` — not because they're "the same site".

### Browser/backend topology

The browser calls the backend **directly** — there is no Next.js
server-side proxy or route handler in between, and no server-held session
state. This keeps there being exactly one auth path (browser ↔ backend),
per the build prompt's "do not accidentally create two incompatible auth
paths" requirement. It also means Next.js `proxy.ts`
(the renamed `middleware.ts`) is deliberately **not** used for auth guarding:
it would have no way to validate the HttpOnly refresh cookie (it's opaque
to any code that isn't the backend) without either duplicating the
backend's JWT validation logic or making a round-trip to the backend on
every navigation — both worse than the client-side check `AuthProvider`
already does. Route protection here is client-side (see `src/app/page.tsx`
for the pattern: render nothing privileged while `status !== "authenticated"`,
redirect once resolved) — a UX behavior, not a security boundary; the
backend's own 401/403 responses remain the actual authorization enforcement,
exactly as "Frontend authorization" below states.

`src/lib/api/topology.ts`'s `assertCsrfHostnameCompatible()` enforces the
hostname-match invariant above at runtime, in the browser only (a no-op
during SSR/build, where there's no `window.location` yet and nothing
CSRF-dependent has run either): before priming/reading the CSRF cookie, it
compares `NEXT_PUBLIC_API_BASE_URL`'s hostname against
`window.location.hostname` (hostname only — ports may legitimately differ
locally) and throws a clear, specific error if they don't match, rather
than letting the CSRF flow fail with an opaque "unable to establish a
secure session" deep in a network call. See
`src/tests/lib/api/topology.test.ts`.

**Local development** (this repo's default): frontend
`http://localhost:3000`, backend `http://localhost:8000` — different
_origins_ (different ports) but the **same hostname** (`localhost`), which
is what actually makes the CSRF cookie readable. Both origins are already
present in the backend's default `CORS_ALLOWED_ORIGINS`/`CSRF_TRUSTED_ORIGINS`
(`backend/config/settings.py`). Verified against the real backend (not
just mocks) during Chunk 2: CSRF priming, login, `/me/`, refresh (rotation
confirmed — old and new access tokens differ), and logout (confirmed the
refresh cookie stops working afterward) all round-tripped correctly over
`curl` against a live `runserver` + the project's Postgres/Redis
containers.

**Production**: the preferred, backend-change-free topology is **same
browser-facing hostname**, split by path via an external reverse
proxy/load balancer this repository doesn't own or package (consistent
with the Phase 17 deployment boundary — the repo doesn't ship the public
TLS proxy, and forwarding headers must be sanitized by whatever does):

```text
https://supportpilot.example.com/            → frontend
https://supportpilot.example.com/api/v1/     → Django backend
```

(`supportpilot.example.com` is a documentation-only illustration — never
put a real domain in committed config.) With this topology,
`NEXT_PUBLIC_API_BASE_URL` is simply the one shared hostname
(`https://supportpilot.example.com`); the generated OpenAPI paths are
already absolute (`/api/v1/...`), so the final request URL is
`https://supportpilot.example.com/api/v1/...` — no doubled prefix, no
extra configuration. The backend's `CORS_ALLOWED_ORIGINS`/
`CSRF_TRUSTED_ORIGINS` need only that one origin.

A sibling-subdomain deployment (`app.example.com` frontend,
`api.example.com` backend — what the backend's own
`.env.production.example` origin illustration might suggest at a glance)
is **not** viable with the backend's current cookie configuration: it's
same-_site_ (the refresh cookie would still be _sent_ correctly), but the
CSRF cookie would not be _readable_ by the frontend's JavaScript (see
"Cookie semantics" above), and every login/refresh/logout attempt would
fail CSRF validation. Making that topology work would require a real
backend change (`CSRF_COOKIE_DOMAIN=".example.com"` and equivalent on the
refresh cookie) — out of scope here per this chunk's "don't change the
backend unless the current contract makes secure integration actually
impossible" constraint, since the same-hostname path-routing topology
above already solves it without one.

## Local development

1. Start the backend (see `../README.md`) so `NEXT_PUBLIC_API_BASE_URL`
   has something to talk to. It must be an origin the backend's
   `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` allow.
2. `npm install`
3. `cp .env.example .env.local` (adjust if the backend isn't on the default port)
4. `npm run dev` and open http://localhost:3000

## Scripts

| Command                           | Purpose                                                               |
| --------------------------------- | --------------------------------------------------------------------- |
| `npm run dev`                     | Start the dev server (Turbopack)                                      |
| `npm run build`                   | Production build                                                      |
| `npm run start`                   | Serve a production build                                              |
| `npm run lint`                    | ESLint                                                                |
| `npm run typecheck`               | `tsc --noEmit`                                                        |
| `npm test`                        | Run the Vitest suite once                                             |
| `npm run test:watch`              | Vitest in watch mode                                                  |
| `npm run format` / `format:check` | Prettier write / check                                                |
| `npm run generate:api-types`      | Regenerate `openapi.yaml` + `src/types/api.ts` from the local backend |
| `npm run check:api-types`         | Fail if the committed files are stale vs. the backend (no writes)     |

## Testing

Vitest + React Testing Library + `jsdom`, configured in
`vitest.config.mts`. Tests live under `src/tests/`, mirroring the directory
they cover (`src/tests/lib/api/errors.test.ts` covers `src/lib/api/errors.ts`,
etc.) rather than living next to source files, so `src/` stays
implementation-only. `NEXT_PUBLIC_API_BASE_URL` is set via Vitest's `test.env`
config (`vitest.config.mts`), not inside `setup.ts` — ESM hoists imports
ahead of any in-file assignment, and `setup.ts` itself transitively imports
modules that read that variable at import time (`src/lib/config.ts`'s
fail-fast validation). `src/tests/setup.ts` registers `jest-dom` matchers,
explicit RTL cleanup between tests, the MSW server lifecycle
(`onUnhandledRequest: "error"` — a forgotten mock is a loud test failure,
not a silent real request), and resets the access token / in-flight-refresh
/ mock-server state before every test so one test's session never leaks
into the next.

**Request-level mocking (`src/tests/msw/`)**: handlers in `handlers.ts`
mirror the real backend contract byte-for-byte where it matters (status
codes, the `{error:{code,message,details?}}` envelope, the CSRF
requirement on login/refresh/logout). One deliberate simplification,
documented in that file: Node's `fetch` doesn't wire a mocked response's
`Set-Cookie` into `document.cookie` the way a real browser would, so the
JS-readable CSRF cookie is set for real (`document.cookie =` inside the
handler, exercising `csrf.ts` unmodified) while the HttpOnly refresh
cookie's presence/validity is tracked as mock server state instead — which
is actually the accurate abstraction, since real frontend code can't see
that cookie's value either way.

Coverage: environment config validation; API error normalization
(well-formed envelope, unknown error code, non-envelope body, network
failure, timeout, and — added in Chunk 2A — that a `204 No Content`
success is never mistaken for a parse error); the request-timeout helper;
`apiClient`'s URL construction and Authorization/CSRF header attachment
(client.test.ts, the regression test for the base-URL doubling defect
below); the core UI primitives' accessibility semantics; the CSRF
hostname-compatibility guard (`topology.test.ts` — matching hostname
allowed for both local-dev and same-host-production shapes, mismatched
hostnames rejected); and the full auth flow — login (success, invalid
credentials, 429, network failure, duplicate-submission guard), session
bootstrap (authenticated, unauthenticated, network-error classification),
coordinated refresh (single refresh for N parallel 401s, retry-exactly-once,
network-vs-invalid-session distinction), the full logout failure matrix
(success; network failure clears local state immediately; network failure
reports `"server_unconfirmed"` and sets the pending marker; a reload while
still pending retries revocation instead of silently re-authenticating; a
later successful attempt clears the marker; a fresh login also clears a
stale marker; nothing resembling a token ever lands in `localStorage`),
redirect-target safety, and that no auth _secret_ ends up in
`localStorage`/`sessionStorage`/a JS-readable cookie (the one thing
`localStorage` does legitimately hold — the boolean logout-pending flag —
is asserted to never look like a token). Workspace-switching and full
route-protection (beyond the single `/` placeholder) land with those
features in later chunks.

## Security notes

See "Authentication" above for the full model (credential storage, refresh
coordination, CSRF, topology). Summary and explicit non-claims:

- **Token storage**: access token in memory only (`token-store.ts`); refresh
  token never touched by frontend code (HttpOnly); CSRF cookie is
  necessarily JS-readable (inherent to the double-submit pattern, not a
  choice this frontend made). `localStorage` holds exactly one
  auth-related value, and it is not a credential: a boolean
  logout-confirmation marker (`logout-intent.ts`) that carries no token,
  user identity, or other secret. Verified by
  `src/tests/features/auth/no-token-leak.test.ts` (including that the
  marker itself never resembles a token) and by manual inspection during
  the real-backend smoke test (Chunk 2) — no auth _secret_ has ever landed
  in `localStorage`/`sessionStorage`.
- **CSRF**: implemented per the backend's actual `enforce_csrf()` contract
  (`src/lib/api/csrf.ts`, `client.ts`'s CSRF middleware) — never disabled,
  never a wildcard trusted origin (that setting lives in the backend anyway,
  not something this frontend could weaken). Its one real topology
  requirement (frontend/backend must share a hostname — see "Cookie
  semantics") is enforced at runtime (`topology.ts`), not just documented.
- **Logout**: never stated as an unqualified guarantee — see "Logout"
  above. The frontend distinguishes, and represents to the user, "signed
  out locally" from "server revocation confirmed"; it does not claim the
  stronger of the two when only the weaker is true.
- **Frontend authorization**: the frontend never decides what a user is
  allowed to do. Hiding a control based on role/permission is a UX
  convenience only — the backend's own RBAC/tenant-scoping response (403/404)
  is authoritative, and the UI must handle receiving one even when it also
  hid the control. Client-side route "protection" (`src/app/page.tsx`,
  `src/app/login/page.tsx`) is the same: a UX redirect based on `AuthProvider`
  state, not a security boundary — see "Browser/backend topology" above for
  why that's an accurate description and not an oversight.
- **What this does _not_ claim**: none of the above makes the frontend
  "XSS-proof" or "CSRF-proof" in an absolute sense, or eliminates token
  theft risk. An XSS vulnerability elsewhere in the app could still read the
  in-memory access token (real for the ~15 minutes it's valid) or the
  CSRF cookie; that's an inherent limit of any browser-based session, not
  something particular to this implementation. The concrete, verifiable
  claims are the ones above: no long-lived secret in persistent storage, no
  secret in a URL, and CSRF enforced per the backend's real contract, not
  bypassed.

## Known defects fixed during Chunk 2A

- **`unwrap()` treated a legitimate `204 No Content` as an error**: every
  logout call was silently ending up in the `"server_unconfirmed"` branch
  — including genuinely successful ones — because `unwrap()`
  (`src/lib/api/request.ts`) treated _any_ response with no parsed `data`
  as a parse failure. A `204` (what `POST /auth/logout/` actually returns)
  legitimately has no body per HTTP semantics; Chunk 2's own logout tests
  didn't catch this because they only asserted `status === "unauthenticated"`,
  which was true either way (local state is cleared regardless of the
  server outcome) — they never checked whether the server call itself had
  actually succeeded. Fixed by special-casing `204`/`304`; regression-tested
  in `src/tests/lib/api/request.test.ts` and the full logout matrix in
  `src/tests/features/auth/logout.test.ts`.
- **Sibling-subdomain production topology was documented as sufficient —
  it isn't**: Chunk 2's README claimed `app.example.com` (frontend) /
  `api.example.com` (backend) would work because they're same-_site_
  (`SameSite=Lax` cookie sending). That's true but irrelevant to the
  actual failure mode: the CSRF cookie's _readability_ by frontend
  JavaScript is governed by its `Domain` attribute against the exact
  hostname, not by site/SameSite — and the backend sets no `Domain`, so a
  sibling-subdomain frontend could never read it, and every
  login/refresh/logout would fail CSRF validation in that topology. See
  "Cookie semantics" above for the corrected documentation, and
  `assertCsrfHostnameCompatible()` (`topology.ts`) for the runtime guard
  that now catches this class of misconfiguration explicitly instead of
  letting it fail as an opaque CSRF error.

## Known defects fixed during Chunk 2

- **Base URL doubling**: Chunk 1's `.env.example` set
  `NEXT_PUBLIC_API_BASE_URL` to `http://localhost:8000/api/v1` — but the
  generated OpenAPI paths (`src/types/api.ts`) are already absolute (e.g.
  `/api/v1/auth/login/`), and `openapi-fetch` joins `baseUrl` + path with no
  de-duplication, producing `.../api/v1/api/v1/...`. This was never
  exercised until the first real request in Chunk 2. Fixed by changing the
  convention to an origin-only base URL (`.env.example`, `config.ts`
  doc comments); regression-tested in `src/tests/lib/api/client.test.ts`.
- **`fetch` captured too early for MSW**: `apiClient` originally passed no
  explicit `fetch` option to `openapi-fetch`, which defaults to capturing
  `globalThis.fetch` once at client-creation time (module import) — before
  MSW's `server.listen()` (a `beforeAll` hook) had a chance to patch it,
  so every mocked test silently hit the real network instead. Fixed by
  resolving `fetch` dynamically per call in `client.ts`.
