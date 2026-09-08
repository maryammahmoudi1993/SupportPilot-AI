# SupportPilot AI — Frontend

The frontend for SupportPilot AI: a Next.js (App Router) application that
consumes the Django/DRF backend in [`../backend`](../backend). This is
**Phase 18** — through Chunk 3, that's framework, design system, typed API
transport, authentication, workspace context, protected routing, and the
application shell. Business-domain feature pages (conversations, customers,
tickets, ...) land in later phases; see
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
tree — a React context (`AuthProvider`) is enough, and none of the
login/logout/me data fetching benefits from a caching layer built for lists
of server records. Workspace state (Chunk 3) is the same shape of problem —
a small membership list already delivered as part of `/me/`, re-derived
whenever that changes — so it's a second plain context (`WorkspaceProvider`),
not a reason to introduce one. Revisit once a later phase's business-domain
pages have real server-list data (pagination, background refetch,
cache invalidation across mutations) that actually benefits from TanStack
Query; `features/workspace`'s doc comments define the workspace-ID-in-query-key
convention those pages should follow once it's added, per the "don't add a
layer for fashion" principle in the build prompt. `msw` was added, but only
as a dev dependency for tests. Two small Radix UI primitives
(`@radix-ui/react-dropdown-menu`, `@radix-ui/react-dialog`) were added in
Chunk 3 for the workspace switcher/user menu and the mobile navigation
drawer — the one place in this codebase where a hand-built component would
mean re-implementing non-trivial keyboard/focus-trap/dismissal behavior
rather than styling an existing correct one (see "Design system" below).

## Directory structure

```
frontend/
  src/
    app/            App Router routes, layouts, and route-level UI states
      (protected)/   Route group for every authenticated route (no URL segment of its own)
        app/         The real authenticated landing route (/app)
      login/         The public login route
    components/
      ui/           Design-system primitives (Button, Input, Card, DropdownMenu, Sheet, ...)
      shell/        Application shell chrome (Sidebar, Header, nav config/links, user menu, mobile nav)
    features/
      auth/          Login/logout/me operations, AuthProvider, LoginForm, redirect safety
      workspace/     Active-workspace state, selection persistence, the workspace switcher
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
them — `auth` and `workspace` are the first two, and the pattern they
establish (a feature owns its API calls, its own React state, and its own
tests; transport-level concerns generic across features stay in `lib/api`;
shell-chrome concerns generic across every authenticated route stay in
`components/shell`) is meant to repeat.

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
  as `{ [key: string]: unknown }[]`. Chunk 3 closes this on the frontend
  side without a backend change: `src/features/workspace/parse.ts`'s
  `parseWorkspaceMemberships()` narrows the raw array to the real
  `{ id, name, slug, role }` shape (verified directly against
  `accounts/serializers.py`'s `WorkspaceMembershipSummarySerializer`, and
  against a live backend during the Chunk 3 smoke test — see "Workspace
  context" below), dropping any entry that doesn't match rather than
  trusting or crash-casting it. This was chosen over adding
  `@extend_schema_field` to the backend serializer (the other option this
  chunk considered) because reusing `/me/`'s already-fetched data avoids a
  second network round trip for the workspace list, and the runtime guard
  costs a handful of scalar-field checks, not a schema-validation
  dependency. A dedicated, fully-typed `GET /api/v1/workspaces/` endpoint
  does exist (`workspaces/views.py`) and was considered as the "prefer a
  better-typed dedicated endpoint" option — it's used directly for
  workspace-scoped detail views, but its response omits the caller's `role`
  in that workspace (only `/me/`'s membership summary carries that), so
  using it as the _list_ source would still need a second call per
  workspace to recover the role. `@extend_schema_field` on the backend
  serializer remains the cleanest long-term fix and is a small, low-risk
  change a future phase can make; it wasn't done here because Chunk 3 can
  consume the current contract safely without it (the "don't change the
  backend unless the current contract makes secure integration actually
  impossible" constraint).

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
- **`timeout.ts` / `request.ts`** — see "Auth request timeout policy" below
  for the full policy; in short, `withRequestTimeout` applies a default 15s
  timeout (`DEFAULT_TIMEOUT_MS`) to a request, combinable with a
  caller-supplied `AbortSignal` (e.g. component unmount); `requestWithTimeout`
  composes that with `unwrap` (which converts an `openapi-fetch`
  `{ data, error, response }` result into throw-on-failure form) into the one
  request path every auth-critical call actually uses. Long-running or
  upload endpoints should pass their own timeout rather than inherit the
  default.
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

### Session state model

`AuthState.status` (`src/features/auth/auth-provider.tsx`) is one of four
explicit values — never fewer, and never inferred from `user === null` or
from the incidental presence of an error field:

| Status              | Meaning                                                                                                                                                                                          | Privileged UI | Routes to `/login`? |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------- | ------------------- |
| `"loading"`         | Bootstrap/revalidate is in flight — nothing is known yet.                                                                                                                                        | No            | No                  |
| `"authenticated"`   | The backend confirmed a valid session.                                                                                                                                                           | Yes           | No                  |
| `"unauthenticated"` | The backend gave a **definitive** verdict of no valid session — a real `authentication_failed` 401 from bootstrap/refresh, or an explicit logout.                                                | No            | **Yes**             |
| `"uncertain"`       | The session could **not be verified** — network failure, timeout, or any backend response that isn't a definitive authentication verdict (`isUncertainSessionError()`, `src/lib/api/errors.ts`). | No            | **No**              |

**Why this needed a fourth state (Phase 18 Chunk 3A):** through Chunk 3, a
network/timeout failure during bootstrap or a mid-session refresh collapsed
into `"unauthenticated"` — the same state a real, confirmed-invalid session
produced — with only an incidental `AuthState.error` field distinguishing
them, and nothing downstream (`ProtectedLayout`, the root route) actually
checked it. The practical effect: a temporary network blip while
determining or refreshing the session redirected the user to `/login` and
told them, in effect, "you're signed out" — which was never established.
`"uncertain"` is deliberately its own state, not encoded as
`status === "unauthenticated" && error !== null`, so no future call site
can make that mistake again by only checking `status`.

**Classification** (`isUncertainSessionError()`) is deliberately
conservative in the "uncertain" direction: only a definitive
`authentication_failed` counts as confirmed-invalid. Every other outcome —
`network_error`/`timeout` (the request never reached the backend at all),
but also e.g. `internal_server_error` or `parse_error` (the backend _did_
respond, but not with an authentication verdict) — is "uncertain": "we
don't know," never silently folded into "logged out."

**Never claim "signed out" without proof; never claim "signed in" without
proof either** — the two directions of the same rule this codebase has
followed since Chunk 2. `"uncertain"` is what makes both hold at once for a
transport failure: the frontend renders `SessionVerificationError`
(`components/shell/session-verification-error.tsx` — a heading, an
explanation, Retry, and an optional Sign out, reusing the existing logout
flow unchanged) instead of either the protected shell or a login redirect,
and offers `AuthProvider.revalidate()` ("Retry") as the recovery path back
to `"authenticated"` or forward to `"unauthenticated"` once the backend can
actually be asked. See "Protected routing and application shell" below for
where this is consumed.

### Session bootstrap and reload

There is deliberately no separate "try refresh, then fetch /me/" bootstrap
sequence. `AuthProvider` just calls `fetchCurrentUser()` on mount; that goes
through `withAccessTokenRetry` (`src/lib/api/session.ts`), which is the
_same_ 401 → refresh → retry mechanism any protected call uses (see below).
On a fresh page load there is no in-memory access token, so the first call
naturally 401s, triggers a refresh via the HttpOnly cookie, and retries —
resolving to `"authenticated"` if a valid refresh cookie survived the
reload, to `"unauthenticated"` if the backend definitively says it didn't
(or has expired), or to `"uncertain"` if the refresh attempt itself
couldn't be completed (network/timeout/unexpected response) — never to
`"unauthenticated"` for that last case. One bootstrap mechanism, not two,
and one classification the mid-session refresh path (below) reuses exactly.

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
in-memory access token and calls `notifySessionExpired(error)`
(`token-store.ts`), passing the classified `ApiError` through — which
`AuthProvider` has registered a handler for, one owner for "something about
the session just changed," transitioning to `"unauthenticated"` for a
definitive `authentication_failed` or to `"uncertain"` for anything else
(the exact same classification bootstrap's own catch block uses). It only
acts if the app was actually `"authenticated"` at that moment, so it can't
clobber an in-flight _first_ bootstrap that's about to commit its own
classification. The refresh request itself is bounded by the same central
timeout mechanism every other auth call uses — see "Auth request timeout
policy" below — so a refresh that never gets a response doesn't leave
`AuthProvider` stuck in `"loading"` forever; the resulting `AbortError` is
exactly what `normalizeTransportError` maps to the `"timeout"` code above.

### Auth request timeout policy

Every auth-critical request is bounded — none of login, refresh, `/me/`,
logout, or CSRF priming can hang the UI indefinitely just because the
server never responds. This wasn't true through Phase 18 Chunk 3A: only
`refresh` had a real timeout wired in, which meant a hung `/me/` request
during bootstrap (arguably the single most common auth-critical call,
firing on every page load) could still leave `AuthProvider` stuck in
`"loading"` forever. Closed in Chunk 3B by routing every one of these calls
through the same central mechanism instead of copying timeout logic into
each:

| Request    | Function                                          | Timeout                          | Notes                                                                                                                                                            |
| ---------- | ------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| CSRF prime | `ensureCsrfCookie()` (`lib/api/csrf.ts`)          | `DEFAULT_TIMEOUT_MS` (15s)       | Bounded once, here — every caller (login/refresh/logout) inherits this automatically, rather than each needing to remember to bound their own CSRF-priming call. |
| Login      | `login()` (`features/auth/api.ts`)                | `DEFAULT_TIMEOUT_MS`             | A hung login no longer leaves the submit button permanently disabled — see "Login" below.                                                                        |
| Refresh    | `ensureFreshAccessToken()` (`lib/api/session.ts`) | `DEFAULT_TIMEOUT_MS`             | Its own window, separate from CSRF-priming's.                                                                                                                    |
| `/me/`     | `fetchCurrentUser()` (`features/auth/api.ts`)     | `DEFAULT_TIMEOUT_MS` per attempt | Invoked up to twice by `withAccessTokenRetry` (initial + retry-after-refresh) — each attempt gets its own bounded window, not one shared budget across both.     |
| Logout     | `logout()` (`features/auth/api.ts`)               | `DEFAULT_TIMEOUT_MS`             | A timeout here is indistinguishable from any other server-revocation failure — see "Logout" below; local state is already cleared before this call even starts.  |

**Mechanism**: `lib/api/timeout.ts`'s `withTimeout(timeoutMs, callerSignal?)`
is the low-level primitive (an `AbortController` that fires after
`timeoutMs`, optionally chained to a caller-supplied signal). `lib/api/request.ts`'s
`withRequestTimeout(fn, timeoutMs?, callerSignal?)` wraps that into
"run `fn` with a bounded signal, always dispose the timer" — the single
reusable combinator every call site above uses, rather than each inventing
its own `setTimeout`/`AbortController` pair. `requestWithTimeout(fn, timeoutMs?)`
further composes that with `unwrap()` for call sites that own their own
`unwrap()` call (login, logout, CSRF priming, refresh); `/me/` uses
`withRequestTimeout` directly instead, since `withAccessTokenRetry` needs
the raw `{data, error, response}` shape itself to detect a 401 and retry.

**Default and override**: every call site above uses the same
`DEFAULT_TIMEOUT_MS` (15s, `client.ts`) — there is currently no per-call
override in real use, though `withRequestTimeout`'s signature supports one
for a future call site that needs a different budget (e.g. a
longer-running upload endpoint in a later phase; this codebase does not
claim every future endpoint will share this timeout, only that these five
auth-critical ones currently do). Tests shrink the effective timeout via a
single test-only override (`__setTimeoutOverrideForTests(ms)`,
`request.ts`) rather than waiting out 15 real seconds per test or each call
site needing its own override hook — reset to `null` (no override) in
`src/tests/setup.ts`'s global `beforeEach`.

**What a timeout produces**: an `AbortError` → `normalizeTransportError()`
→ a `"timeout"`-coded `ApiError`, classified by `isUncertainSessionError()`
exactly like a plain network failure (see "Session state model" above) —
never as proof the session or credentials are invalid.

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
or a later attempt succeeds. A timeout is just one more way that server
call can fail — bounded by the same central mechanism as every other auth
request (see "Auth request timeout policy" above) — and is handled
identically to a network outage: `"server_unconfirmed"`, pending marker
set, no indefinite wait for a response that's never coming.

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

## Workspace context

`src/features/workspace/workspace-provider.tsx`'s `WorkspaceProvider` (used
only inside the `(protected)` route group — see "Protected routing" below)
tracks which of the current user's workspace memberships is active. It is
a second, deliberately separate context from `AuthProvider`: authentication
answers "who is this", workspace answers "which tenant are they currently
looking at", and the build prompt's own rule ("do not leak workspace
selection state into AuthProvider") is a real architectural boundary, not
just a style preference — a later phase's business-domain pages depend on
being able to reason about "is there a session" and "which workspace" as
independent questions.

**Contract** (discovered from the real backend, not invented):

| Question                                             | Answer                                                                                                                                                                                                                                                                    |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Where does the membership list come from?            | `GET /api/v1/auth/me/`'s `workspaces` field — already fetched by `AuthProvider`'s bootstrap; no second request.                                                                                                                                                           |
| Membership shape                                     | `{ id: uuid, name, slug, role }` per workspace (`accounts/serializers.py` `WorkspaceMembershipSummarySerializer`) — see the schema-gap note above for how the untyped generated field is narrowed.                                                                        |
| How is the active workspace conveyed to the backend? | A **URL path parameter** — every workspace-scoped endpoint is `/api/v1/workspaces/<uuid:workspace_id>/...` (`workspaces/urls.py`). There is no header, query parameter, or request-body convention; nothing was invented (no `X-Workspace-ID` header exists).             |
| What enforces access to a workspace?                 | The backend, on every request, from the database (`workspaces/selectors.py`'s `get_workspace_for_user_or_404`) — a workspace the caller isn't an active member of 404s (never 403 — no existence leakage), regardless of what the frontend's active-workspace state says. |

**State model** — `WorkspaceStatus` is one of `"idle" | "loading" | "error" | "empty" | "ready"`,
deliberately not fewer: `"idle"` (confirmed unauthenticated — nothing to
load) and `"error"` (`AuthStatus === "uncertain"`: the session itself
couldn't be _verified_ — see "Session state model" above) are both
distinct from `"empty"` (session confirmed, genuinely zero memberships) —
collapsing any of these into a shared `null` would mean either showing "you
have no workspace" during a network outage, or the reverse. `"error"` is
keyed off `auth.status` directly, not merely `auth.error` being non-null —
see "Known defects" below for the bug this replaced.
`WorkspaceGate` (`components/shell/app-shell.tsx`) renders
a distinct UI for each.

**Selection and persistence**: on becoming authenticated (or whenever the
membership list changes), the active workspace is chosen by: (1) keep the
current selection if it's still in the list; (2) otherwise restore a
previously-persisted selection (`localStorage["sp_active_workspace_id"]`) if
it's still accessible; (3) otherwise fall back to the first
server-provided workspace; (4) a persisted ID that resolves to neither is
discarded, not silently kept. The persisted value is a workspace UUID —
already treated as a non-secret, security-safe identifier throughout the
backend (`workspaces/models.py`) — never an authorization decision or a
credential; switching it changes what the frontend _asks for_, never what
the backend _permits_ (see "Server is authoritative" — this is restated
deliberately, since it's the one invariant every other guarantee in this
section depends on). `localStorage`, not `sessionStorage`, because the
preference should survive a reload/new tab like any other UI preference;
it is scoped per browser profile, not per account, so a different account
signing in on the same browser simply finds it absent from its own
membership list and falls back per rule (4) above. It is deliberately
**not** cleared on logout — a returning user on the same browser/account
gets the same workspace restored, which is exactly the UX benefit this
preference exists for, and rule (4) already makes it safe for any other
case.

**Switcher** (`features/workspace/workspace-switcher.tsx`) is a Radix
dropdown-menu — current workspace name plus role, a list of the caller's
other accessible workspaces, and the three non-`"ready"` states above each
rendered explicitly (a loading skeleton, an "unavailable" message, an
"no workspace available" message) rather than a switcher that silently
looks broken.

## Protected routing and application shell

**Route groups**: `src/app/(protected)/` is a Next.js route group (its
folder name doesn't appear in the URL) — every authenticated route lives
under it and shares its layout; `src/app/login/` stays outside it. The one
real destination so far is `src/app/(protected)/app/page.tsx` → `/app`.

`src/app/(protected)/layout.tsx` is the actual protection boundary,
matching `AuthStatus` exactly — all four states, not three:

- `"loading"` → render nothing privileged (a bare spinner), not the shell,
  even briefly.
- `"unauthenticated"` → `router.replace("/login")`. A **definitive** backend
  verdict of no valid session — this also covers that verdict arriving
  _while the user is already on an authenticated route_ (a real
  `authentication_failed` from a mid-session refresh): `AuthProvider`'s
  transition to `"unauthenticated"` unmounts the shell (and, inside it,
  `WorkspaceProvider` and every child) on the very next render, before this
  effect even runs — there is no window where stale privileged content
  stays mounted with a confirmed-invalid session.
- `"uncertain"` → render `SessionVerificationError`
  (`components/shell/session-verification-error.tsx`), **not** a redirect
  to `/login` and **not** the shell. See "Session state model" above —
  network/timeout/an unexpected response is never treated as proof the
  session is invalid, whether it happens during initial bootstrap or mid-app
  (a corrected model as of Phase 18 Chunk 3A — see "Known defects" below
  for what this replaces). This still removes all privileged content (it
  isn't `"authenticated"` either), just without claiming the user is signed
  out, and without redirecting off a transport failure.
- `"authenticated"` → render `WorkspaceProvider` wrapping `AppShell`.

As with Chunk 2's `/login` ↔ authenticated redirect, this is a **UX
convenience, not the security boundary** — see "Browser/backend topology"
above; nothing here changes that model, it just adds routing for a third
outcome (transport uncertainty) alongside the original two.
`src/app/page.tsx` (the bare root route) mirrors the same three-way split:
`"authenticated"` → `/app`, `"unauthenticated"` → `/login`,
`"uncertain"` → the same `SessionVerificationError` screen (an earlier
version of this route left `"uncertain"` on an unrecoverable infinite
spinner — fixed alongside `ProtectedLayout`, see "Known defects" below).
Neither route ever redirects on `"uncertain"`, so there is no bounce
between `/app` and `/login` off a transport failure.

**Recovery**: `SessionVerificationError`'s Retry button calls
`AuthProvider.revalidate()` — the same bootstrap function used on mount,
re-run on demand. A successful retry resolves to `"authenticated"` (the
shell/`WorkspaceProvider` remount cleanly — no duplicate providers, since
`ProtectedLayout` only ever renders one tree per status) or to
`"unauthenticated"` (routes to `/login`) depending on what the backend
actually says this time; a retry that fails the same way leaves the status
at `"uncertain"` with no redirect and no loop. The screen also offers an
optional "Sign out," reusing the existing `logout()` flow unchanged
(including the `complete`/`server_unconfirmed` distinction from Chunk 2A —
there is no second logout implementation for this state).

**Application shell** (`components/shell/`): `AppShell` owns the app
landmarks (`<aside>` sidebar, `<header>`, `<main id="main-content">` — the
`Skip to main content` link's actual target once inside a protected route),
the mobile navigation drawer, and `WorkspaceGate` (the loading/error/empty/
ready branch for workspace state, `error` keyed off `AuthStatus === "uncertain"`
— see "Workspace context" above). In practice `ProtectedLayout` never
renders `AppShell` at all while `"uncertain"` (see above), so this branch is
defense in depth rather than the primary mechanism — kept because
`WorkspaceProvider`/`AppShell` stay correct on their own terms regardless of
how they're mounted. It owns
no business-domain content — every child route brings its own, starting
with `(protected)/app/page.tsx`, the minimal authenticated landing route
showing only real backend-sourced data (signed-in user, active workspace,
role, membership count) and explicitly no fabricated product metrics
(ticket counts, SLA, resolution rate, ...).

**Navigation** (`components/shell/nav-config.ts`) is a small typed array —
one entry (`Overview` → `/app`) for now. Future business-domain
destinations get a stable `id`/`path` entry here once their route actually
ships; the list intentionally does not contain unclickable placeholder
entries for conversations/customers/tickets/etc. — an unclickable nav item
is worse than a short sidebar. The active route is marked both visually
(background fill, left border, font weight — not color alone) and
accessibly (`aria-current="page"`, `NavLinks` in `components/shell/nav-links.tsx`).

**Client/server boundaries**: `"use client"` is scoped to the pieces that
actually need browser APIs or React state — `AuthProvider`,
`WorkspaceProvider`, `ProtectedLayout` (reads `auth.status`), the
switcher/menu/drawer components (Radix primitives, `useState`), and
`NavLinks` (`usePathname`). `Sidebar` and `Header` themselves stay plain
Server-Component-compatible functions (no hook of their own) even though
they're rendered from a client parent — they just don't need the directive.
No route under `(protected)` attempts server-side JWT validation or a
second, Next-held session: see "Browser/backend topology" above, which this
chunk doesn't change.

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
is asserted to never look like a token).

Added in Chunk 3: `parseWorkspaceMemberships()`'s malformed-payload
handling (missing/wrong-typed fields, unknown role values — each dropped,
never crash-cast); the full `WorkspaceProvider` state matrix (idle, ready,
empty, error-vs-empty distinction, default/persisted/stale-persisted
selection, switch + persistence, ignoring a switch to a non-member
workspace, clearing on logout, clearing on a mid-session auth expiry); the
workspace switcher and user menu (real identity/role display, keyboard
operation, logout invoking the existing complete/`server_unconfirmed`
flow); the mobile navigation drawer (open/close, Escape-to-close-and-
return-focus, closing on navigation); `ProtectedLayout` (no privileged
flash while loading, redirect only on a _confirmed_ unauthenticated
verdict, rendering the shell once authenticated, unmounting it on a
confirmed mid-session expiry, exactly-once redirect with no loop); the
root route and login-page redirects for an already-authenticated visitor;
and the explicit login-supersedes-a-pending-logout-marker regression across
a full login → reload cycle (`auth-provider.test.tsx`).

Added in Chunk 3A: the full session-uncertainty matrix — initial-bootstrap
network failure and (real, abort-driven, not simulated) timeout both
resolving to `"uncertain"`, never `"unauthenticated"`
(`auth-provider.test.tsx`); a real 401 still resolving to confirmed
`"unauthenticated"` (unchanged from Chunk 3, re-verified alongside the new
cases so the two can't silently collapse into each other again);
`ProtectedLayout` rendering `SessionVerificationError` (not a redirect, not
the shell) for both an initial-bootstrap and a mid-session network failure;
Retry from `"uncertain"` resolving to `"authenticated"` (shell restored),
to `"unauthenticated"` (redirected), or remaining `"uncertain"` (network
still down, no loop) depending on what the backend actually says
(`protected-layout.test.tsx`); `SessionVerificationError`'s own
accessibility (semantic heading, Retry keyboard-reachable and
Enter-activatable, Sign-out reusing the existing logout flow —
`session-verification-error.test.tsx`); and that
`WorkspaceProvider`/parallel-refresh-dedup/logout-pending/redirect-safety
all remain green under the new state model (re-run, not just assumed
unaffected).

Added in Chunk 3B: a hung `/me/` after a successful refresh resolving to
`"uncertain"` (not an infinite spinner) and Retry recovering to
`"authenticated"` once `/me/` actually answers (`auth-provider.test.tsx`
"3B.A", `protected-layout.test.tsx` "H"); a hung login leaving the form
usable again with a "took too long" message, not a permanently-disabled
button (`login-form.test.tsx` "B"); a hung logout still reporting
`server_unconfirmed` with local state already cleared
(`logout.test.ts` "C"); a hung CSRF-priming request bounded on its own
(`csrf.test.ts` "D" — this module's first dedicated test file); the
conservative classification rule locked in against `internal_server_error`
and a genuinely malformed/empty response, not just network/timeout
(`auth-provider.test.tsx` "E"/"F"); and the root route's own `"uncertain"`
rendering, closing a gap the Chunk 3A report itself flagged as untested
(`root-page.test.tsx` "G").

## End-to-end tests (`e2e/`, Phase 18 Chunk 4)

Playwright (`@playwright/test`), Chromium only — the mandatory acceptance
browser for this phase; Firefox/WebKit weren't added (single-browser
coverage was judged sufficient for a foundation-only phase, not a gap
worth the added CI time). Config: `playwright.config.ts`.

**Runs against the real backend**, not mocks: `e2e/global-setup.ts` shells
out to `manage.py shell` to create two synthetic users (one with two real
workspace memberships — owner + support_agent — one with zero) directly in
the project's Postgres container, and `e2e/global-teardown.ts` deletes them
unconditionally afterward (also self-healing: setup wipes any `e2e-*`/`E2E *`
leftovers from a prior aborted run before creating fresh ones).
`playwright.config.ts`'s `webServer` array starts both halves itself —
Django (`manage.py runserver`) and the frontend built and started in
**production mode** (`next build && next start`, not `next dev`) — so the
suite is self-contained given only `docker compose up -d db redis` already
running. Playwright's own request interception (`page.route()`) is used
only for the narrow set of failure cases impractical to induce against a
healthy real backend (a hung or aborted request) — every genuine
login/refresh/workspace/logout flow is the real HTTP round trip.

**E2E-only backend throttle override**: `AUTH_LOGIN_THROTTLE_RATE` and
`AUTH_REFRESH_THROTTLE_RATE` are raised (via `webServer`'s `env`, not a
backend file) for the E2E backend process only. Both are already
environment-driven settings (`config/settings.py`, defaults `10/min`/`30/min`
— the same mechanism as `DATABASE_URL`/`ALLOWED_HOSTS`), calibrated for
production abuse-prevention against a single real user, not the volume a
real-browser suite legitimately generates in a few minutes (every page
load bootstraps via a real refresh call too). No backend code, no backend
setting, and no security *logic* changes — CSRF, credential checks, and
cookie issuance/rotation are exercised completely unmodified; only the
request-volume threshold differs for this process.

**Coverage**: real-browser login (CSRF prime → login → refresh cookie
received, HttpOnly, access token never in storage/URL) and its
invalid-credentials path; reload restoration via the refresh cookie alone;
logout (shell gone, server cookie revoked, a failed/aborted logout still
clears local state and reports `"server_unconfirmed"` honestly, pending-marker
recovery, explicit-login-supersedes-pending-logout); the full session-
uncertainty matrix (initial and mid-session network failure,
`/me/`-only failure, Retry to valid/invalid/still-uncertain); real
workspace load/switch/persistence/reload, a stale persisted workspace ID
discarded safely, and the zero-workspace no-crash state; protected routing
(unauthenticated → `/login`, safe/unsafe `?next`, authenticated → `/login`
redirect); a responsive sweep at 375×812/768×1024/1280×800/1440×900 (no
horizontal overflow) plus a dedicated mobile-drawer and desktop-layout
check; and an axe accessibility scan (0 serious/critical required) across
`/login`, authenticated `/app`, the zero-workspace state, and
`SessionVerificationError`, plus a keyboard-only pass over the login form,
workspace switcher, and user menu.

**Login volume, deliberately kept realistic rather than exhaustive**: even
with the throttle raised, a handful of tests (routing's `?next` cases, the
keyboard-login-form pass) are real UI-driven logins rather than reusing a
saved session, because they test the login flow itself. An earlier design
tried reusing one Playwright `storageState` snapshot across many tests to
minimize login volume — this broke: the backend rotates the refresh token
on every use and blacklists the old one (`ROTATE_REFRESH_TOKENS`/
`BLACKLIST_AFTER_ROTATION`, real, correct security behavior), so a second
test loading the same frozen snapshot found its cookie already invalid.
Reverted in favor of plain per-test logins, which is both simpler and a
more realistic acceptance test than an optimization that fights the
backend's own security model.

Run with `npm run e2e` (`npm run e2e:report` opens the last HTML report).
`playwright-report/`, `test-results/`, and `e2e/.e2e-data.json` are
gitignored — no committed run artifacts, no persisted auth tokens.

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
  `src/app/login/page.tsx`, `src/app/(protected)/layout.tsx`) is the same: a
  UX redirect based on `AuthProvider` state, not a security boundary — see
  "Browser/backend topology" above for why that's an accurate description
  and not an oversight. The same applies to the active-workspace selector
  (`WorkspaceProvider`): it's UX state that changes what the frontend
  _requests_, never what the backend _permits_ — see "Workspace context"
  above and "Server is authoritative" in the Chunk 3 spec.
- **What this does _not_ claim**: none of the above makes the frontend
  "XSS-proof" or "CSRF-proof" in an absolute sense, or eliminates token
  theft risk. An XSS vulnerability elsewhere in the app could still read the
  in-memory access token (real for the ~15 minutes it's valid) or the
  CSRF cookie; that's an inherent limit of any browser-based session, not
  something particular to this implementation. The concrete, verifiable
  claims are the ones above: no long-lived secret in persistent storage, no
  secret in a URL, and CSRF enforced per the backend's real contract, not
  bypassed.

## Known defects fixed during Chunk 3

- **`AuthProvider.error` was set for every unauthenticated outcome, not
  only an uncertain one**: the doc comment on `AuthState.error` always said
  it should mean "the network failed, we don't actually know if the
  session is valid" — but bootstrap's catch block set it for _any_
  `ApiError`, including an entirely ordinary "no refresh cookie exists"
  `authentication_failed` 401 on a plain first visit. This was latent and
  untested in Chunk 2/2A (no existing test asserted `error` was `null` for
  the plain "no session" case) and surfaced only once `WorkspaceProvider`'s
  new `"error"` status (which keys off `auth.error`) made a brand-new,
  never-visited browser incorrectly report "workspace unavailable" instead
  of the correct "not logged in". Fixed by a new
  `isUncertainSessionError()` helper (`lib/api/errors.ts`, checking for
  `network_error`/`timeout` specifically) that both `AuthProvider` and
  `WorkspaceProvider` key off; regression-tested in `auth-provider.test.tsx`
  ("does not report an error for an ordinary confirmed-absent session").

## Known defects fixed during Chunk 3A

- **A network/timeout failure while determining or refreshing the session
  was treated the same as a confirmed logout**: `AuthStatus` had only three
  values, so a transport failure — during initial bootstrap or mid-app —
  had to collapse into `"unauthenticated"`. `ProtectedLayout` (and, worse,
  the bare root route, which didn't even redirect — an unrecoverable
  infinite spinner) then routed the user straight to `/login`, an
  unqualified "you are signed out" the frontend had no actual proof of, on
  nothing more than a dropped connection. Fixed by adding a fourth explicit
  state, `"uncertain"` (see "Session state model" above), classified the
  same conservative way in both the initial-bootstrap and mid-session paths
  (`isUncertainSessionError()`, widened in this same chunk — see below —
  and now the sole authority `notifySessionExpired(error)` and bootstrap's
  own catch block both defer to); `ProtectedLayout` and the root route both
  render a dedicated recoverable `SessionVerificationError` screen instead
  of redirecting. Regression-tested extensively: initial bootstrap
  network/timeout failure (`auth-provider.test.tsx`, `protected-layout.test.tsx`),
  mid-session network failure, Retry succeeding/failing/still-uncertain
  (`protected-layout.test.tsx`), and that neither `/app` nor `/login` ever
  redirects off `"uncertain"` (no bounce).
- **`isUncertainSessionError()` itself was still too narrow**: introduced in
  Chunk 3 to fix the previous defect above, it only recognized
  `network_error`/`timeout` as uncertain — meaning an unexpected non-auth
  backend response (e.g. `internal_server_error`, `parse_error`) during
  bootstrap/refresh would still have been misclassified as a confirmed
  invalid session, the same category of bug one level down. Corrected to
  the inverse, more conservative rule: only a definitive
  `authentication_failed` counts as confirmed-invalid; everything else is
  uncertain. No dedicated regression test targets `internal_server_error`
  specifically (the existing MSW mocks don't simulate one on
  bootstrap/refresh), but the network/timeout tests exercise the same code
  path and the classifier itself is a one-line, directly-reviewable
  inversion.
- **No request timeout was ever actually wired into the transport**:
  `lib/api/timeout.ts`'s `withTimeout`/`withRequestTimeout` and
  `client.ts`'s `DEFAULT_TIMEOUT_MS` existed since Chunk 2 but were never
  attached to a real request — meaning a hung `POST /auth/refresh/` (a
  backend stall, a proxy silently dropping the response, ...) would have
  left `AuthProvider` in `"loading"` forever, with no failure to ever
  classify as `"uncertain"` in the first place. Fixed by wiring
  `withTimeout(DEFAULT_TIMEOUT_MS)` into `ensureFreshAccessToken()`'s
  refresh call (`session.ts`); verified against a real abort (not a
  simulated error) in `auth-provider.test.tsx`'s "B. initial bootstrap
  timeout" test, using a test-only timeout override
  (`__setRefreshTimeoutMsForTests`) rather than waiting out the real 15s in
  every test run. This fixed `refresh` specifically, but not `/me/`, login,
  logout, or CSRF priming — closed for all of them in Chunk 3B below, which
  also replaced this local per-function override with a single shared one
  (`__setTimeoutOverrideForTests`, `request.ts`) once four call sites needed
  the same kind of override.

## Known defects fixed during Chunk 4 (final frontend acceptance gate)

- **`Alert`'s warning variant failed WCAG AA color contrast**: caught by a
  real axe scan (`e2e/accessibility.spec.ts`) against the actual rendered
  `SessionVerificationError` state — `components/ui/alert.tsx` applied a
  `text-current/90` opacity to the body text, which softened
  `text-warning-700` against `bg-warning-50` just enough to drop the
  contrast ratio to 4.06:1 (WCAG AA requires 4.5:1). This had shipped
  unnoticed since Chunk 1 — the component-level tests never measured
  contrast, only DOM structure/roles. Fixed by removing the opacity
  modifier (`text-current`, full opacity) — every variant's `-700` text
  color already provides sufficient contrast against its `-50` background
  on its own; the opacity added no accessibility value.
- **A real end-to-end run of ~25+ tests reliably exhausted the backend's
  real login/refresh rate limits** (`AUTH_LOGIN_THROTTLE_RATE` 10/min,
  `AUTH_REFRESH_THROTTLE_RATE` 30/min — both real, correctly-functioning
  production abuse-prevention, not a bug): every authenticated E2E test
  performs at least one real login, and every `/app` visit bootstraps via a
  real refresh call, so a several-minute suite legitimately exceeds
  per-minute thresholds calibrated for a single human user. Manifested as
  cascading, unrelated-looking test failures (timeouts, 429s) with no
  connection to the feature under test. Fixed by overriding both rates via
  environment variables passed to the E2E backend process only (`webServer`
  in `playwright.config.ts`) — no backend file or production default
  changed. An earlier attempt to reduce login volume by reusing one
  Playwright `storageState` snapshot across many tests looked like the
  "correct" fix but was actually wrong: it broke on the *second* test to
  use a saved snapshot, because the backend rotates the refresh token on
  every use and blacklists the old one — correct, intentional security
  behavior this fix must not (and does not) touch.
- **Two E2E test-authoring bugs, not product defects**, caught by early
  failed runs: `getByRole("alert")` matched both the login form's own error
  alert and Next.js's built-in route-announcer element (also `role="alert"`)
  — fixed by scoping to `page.locator("main").getByRole("alert")`. A test
  assumed workspace "A" (created first) would be the default active
  workspace; the real, correct backend ordering (`-created_at`, so the
  *most recently created* membership sorts first) makes workspace "B" the
  actual default — fixed by asserting against the real ordering instead of
  an assumed one.
- **A test asserted the wrong post-logout Back-button behavior**: expected
  `page.goBack()` to show the login form. In this app both the post-login
  and post-logout redirects use `router.replace()` (never `push()`), so
  `/app` never becomes its own distinct, back-traversable history entry —
  a *stronger* safety guarantee than the test assumed (there is nothing
  privileged to go back to at all, not merely stale content), but it means
  `goBack()`'s actual destination depends on whatever history existed
  before the test's session and isn't reliably `/login`. Fixed by asserting
  the actual invariant that matters (the privileged shell never
  reappears) and using an independent fresh navigation, not a reload of
  Back's unpredictable destination, to confirm the session stays gone.

## Known defects fixed during Chunk 3B

- **Only `refresh` had a real request timeout — `/me/`, login, logout, and
  CSRF priming did not**: Chunk 3A's fix (above) closed the timeout gap for
  exactly one of five auth-critical requests. `/me/` was the most exposed:
  it fires on every bootstrap (every page load), so a hang there was at
  least as likely as one on `refresh` — and CSRF priming was doubly exposed,
  since it's a hidden prerequisite _inside_ `refresh`'s own flow that
  wasn't covered by `refresh`'s new timeout either (the timeout signal was
  only ever passed to the refresh `POST`, not to `ensureCsrfCookie()`'s GET
  that runs first). Fixed by centralizing: `ensureCsrfCookie()` now bounds
  its own request internally (so every caller — login, refresh, logout —
  inherits it automatically), and `login()`/`logout()`/`fetchCurrentUser()`
  each route their main request through the same `requestWithTimeout`/
  `withRequestTimeout` mechanism `refresh` already used, rather than four
  independent `setTimeout`/`AbortController` implementations. See "Auth
  request timeout policy" above for the resulting per-call table.
  Regression-tested per call site: `auth-provider.test.tsx` ("3B.A", a hung
  `/me/` after a successful refresh), `login-form.test.tsx` ("B", a hung
  login leaves the form usable again), `logout.test.ts` ("C", a hung
  logout still reports `server_unconfirmed`), `csrf.test.ts` ("D", a hung
  CSRF prime is bounded on its own).
- **`isUncertainSessionError()`'s conservative-rule fix (Chunk 3A) had no
  regression test locking it in** — only reviewed, not tested, per that
  chunk's own report. Closed with `auth-provider.test.tsx` "E"
  (`internal_server_error` during bootstrap → `"uncertain"`) and "F" (a
  malformed/empty response during bootstrap → `"uncertain"`, exercising
  `unwrap()`'s real `parse_error` path via a genuinely empty 200 response
  rather than a synthetic one).
- **The root route's `"uncertain"` handling (Chunk 3A) had no dedicated
  test** — also noted, not closed, in that chunk's own report (D2). Closed
  with `root-page.test.tsx` "G".

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
