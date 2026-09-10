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
          customers/          Customers list (/app/customers)
            [customerId]/     Customer detail (/app/customers/:id)
          inbox/              Conversation list (/app/inbox)
            [conversationId]/ Conversation detail + message timeline (/app/inbox/:id)
          tickets/            Ticket list (/app/tickets)
            [ticketId]/       Ticket detail (/app/tickets/:id)
      login/         The public login route
    components/
      ui/           Design-system primitives (Button, Input, Card, DropdownMenu, Sheet, ...)
      shell/        Application shell chrome (Sidebar, Header, nav config/links, user menu, mobile nav)
      support/      Shared operational UI, reused across every business domain (EntityNotFound,
                    ListError, Pagination, Timestamp, EnumBadge, CustomerRefLink) — see
                    "Operational Support Workspace" below
    features/
      auth/          Login/logout/me operations, AuthProvider, LoginForm, redirect safety
      workspace/     Active-workspace state, selection persistence, the workspace switcher
      customers/     Customers domain: typed API boundary, query-key factory, React Query hooks,
                     URL-state (de)serialization, and the list/detail page components
      conversations/ Conversations/messages domain: same shape as customers, plus the message
                     timeline, status/channel badge components, and RelatedConversationsPanel
                     (a Customer-detail contextual panel)
      tickets/       Tickets domain: same shape again, plus status/priority badge components and
                     RelatedTicketsPanel (a Customer-detail contextual panel) — see "Tickets +
                     cross-domain operational navigation" below
    lib/            Framework-agnostic code: API transport, config, utils
      api/           Central HTTP client, token/session/CSRF handling, error normalization
      query/         Server-state (TanStack Query) client factory and provider — see
                     "Operational Support Workspace" below
    types/          Generated types only (api.ts) — never hand-edited
    tests/          Vitest specs, mirroring the src/ layout they cover
      msw/           Request-level mocks for the auth, customers, conversations, and tickets
                     endpoints
      support/       Shared test helpers (e.g. renderAuthenticated)
  scripts/          Node scripts (API type generation, drift check)
  openapi.yaml      Generated OpenAPI schema snapshot (see below)
```

Other feature domains (agents, approvals, knowledge, integrations,
evaluations, settings) get their own directories under `src/features/`
starting in the phase that implements them — `auth`, `workspace`,
`customers` (Phase 19 Chunk 1), `conversations` (Phase 19 Chunk 2), and
`tickets` (Phase 19 Chunk 3) establish the pattern: a feature owns its API
calls, its own React state, and its own tests; transport-level concerns
generic across features stay in `lib/api` (and, as of Chunk 1, `lib/query`);
shell-chrome and cross-domain
operational UI concerns stay in `components/shell` and `components/support`
respectively. A cross-domain reference component used by more than one
feature (e.g. `CustomerRefLink`, linked to by both Conversations and
Tickets) lives in `components/support`, not duplicated per-feature.

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

## Operational Support Workspace (Phase 19)

Phase 19 is the first business-product frontend phase: an authenticated
operator uses SupportPilot AI to browse real customers, conversations, and
tickets. Chunk 1 implements the first slice — **Customers** — and the
server-state foundation the rest of Phase 19 builds on.

### Server-state strategy

Phase 18 deliberately shipped without a server-state library — one route
(`/app`) reading data already fetched by `AuthProvider` didn't justify one.
Phase 19 does: multiple lists, detail pages, pagination, filters, and
cross-domain navigation, all workspace-scoped and all needing cache
invalidation that a hand-rolled `useEffect`/`useState` per page would either
duplicate or get subtly wrong (stale data across a workspace switch, a
list not refreshing after a mutation, races between a fast filter change
and a slow request). **TanStack Query v5** (`@tanstack/react-query`) is
introduced in Chunk 1, at the point this actually starts to matter, not
speculatively ahead of it.

`src/lib/query/query-client.ts` (`createQueryClient()`) defines the
project's retry policy explicitly rather than accepting the library
default:

- `network_error`, `timeout`, and `internal_server_error` are the only
  retried outcomes — bounded to 2 retries with a fast, capped backoff
  (200ms, then 400ms; the library default is `1000 * 2^attempt` up to 30s,
  which would leave an operator staring at a spinner for seconds over one
  transient blip).
- Every other `ApiError` code (`validation_error`, `permission_denied`,
  `not_found`, `conflict`, `rate_limited`, `invalid_request`,
  `parse_error`, `unknown_error`) is a definitive outcome — never retried.
- `authentication_failed` is explicitly excluded: a 401 that reaches a
  query already survived `lib/api/session.ts`'s own coordinated
  refresh-and-retry-once. Retrying it again here would just race that
  mechanism; a *definitive* 401 is handled by `AuthProvider`'s
  session-expired handler (clearing the session, redirecting to `/login`),
  not by a query retry.
- Mutations never retry (`retry: false`) — an ambiguous automatic retry of
  a state-changing request (was it applied once, or twice?) is worse than
  a surfaced error the operator can act on. Phase 19 Chunk 1 ships no
  mutations yet (Customers is read-only — see below); this policy is
  in place for the write endpoints later chunks/domains add.
- `refetchOnWindowFocus`/`refetchOnReconnect` are off: an operator asks for
  fresh data by navigating or pressing an explicit Retry, not via an
  implicit background refetch — and the defaults fight determinism in
  tests for no real product benefit here.

`src/lib/query/query-provider.tsx` (`QueryProvider`) owns exactly one
`QueryClient` instance, mounted inside `ProtectedLayout` — *inside* the
`auth.status === "authenticated"` branch, alongside `WorkspaceProvider`
(see `app/(protected)/layout.tsx`). This is what gives session-scoped cache
isolation for free: `ProtectedLayout` renders entirely different JSX for
every other `AuthStatus`, so `QueryProvider` (and therefore every cached
query) unmounts completely on logout or a confirmed mid-session expiry, and
remounts fresh — with an empty cache — on the next login. There is no
cache to leak between sessions because the `QueryClient` itself is gone,
not merely invalidated. A **workspace switch**, by contrast, happens
*within* one authenticated session and must not tear this down — isolation
there is the query-key factories' job (below), not this provider's.

### Workspace-scoped query keys

Every domain gets a typed key factory (see
`src/features/customers/query-keys.ts` for the customers one) whose keys
all embed the active workspace ID as their second segment:

```
["workspaces", workspaceId, "customers", "list", params]
["workspaces", workspaceId, "customers", "detail", customerId]
```

This is the actual mechanism behind "Workspace A's cached data never
renders under Workspace B": a workspace switch changes every hook's
`queryKey`, so React Query treats it as a *disjoint* cache entry, not the
same entry gone stale — there's no shared bucket a stale value could leak
out of. The one place this needs extra care is `placeholderData`
(`src/features/customers/queries.ts`, `useCustomerListQuery`): React
Query's `keepPreviousData` helper reuses the *previous successful query's*
data across ANY key change, including a workspace switch — which would
flash Workspace A's rows for a moment while Workspace B's request is in
flight. Instead, `useCustomerListQuery` reuses `placeholderData` only when
the *previous* query's key carries the *same* workspace ID as the current
one (still giving smooth in-workspace pagination/filtering, never a
cross-tenant flash) — covered by
`customers-list-page.test.tsx`'s workspace-switch test, which asserts the
old workspace's customer name is gone from the DOM immediately on switch,
not merely eventually.

### Customer API contract

| Question             | Answer                                                                                                                                                                   |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| List                  | `GET /api/v1/workspaces/{workspace_id}/customers/` — `customers/views.py` `CustomerListCreateView`, any active member.                                                 |
| Detail                | `GET /api/v1/workspaces/{workspace_id}/customers/{customer_id}/` — `CustomerDetailView`. A customer belonging to a different workspace 404s exactly like one that never existed (`customers/selectors.py customer_get_for_workspace_or_404`) — never a 403, no existence leakage. |
| Pagination            | Backend-standard `PageNumberPagination` (`common/pagination.py`) — `{count, next, previous, results}`, `page`/`page_size` query params, default page size 50, max 500. |
| Search                | A single `search` query param, `icontains` across display/first/last name, email, phone, and external ID (`customers/selectors.py customer_list_for_workspace`) — no explicit-submit contract, so the UI debounces type-ahead (300ms) rather than firing per keystroke. |
| Filters               | `is_active` (boolean) — real and backend-tested, surfaced as a Status select (All/Active/Inactive).                                                                    |
| Sort                  | None. `ordering` appears in the generated OpenAPI schema only because `OrderingFilter` is in the project's global `DEFAULT_FILTER_BACKENDS` — the view sets no `ordering_fields`, so the backend silently ignores it. The frontend never sends it (see the comment in `features/customers/api.ts`) — sending an unsupported control would be building UI for a capability that doesn't exist. |
| Create/update         | `POST`/`PATCH` exist on the backend (`CustomerWriteSerializer`) but are out of Chunk 1's scope — the Customers UI is intentionally **read-only** for now; a real write UI is better deferred than faked. |

**Schema gap (Category A — typing deficiency, not a missing capability)**:
`is_active` is a real, tested filter the view reads directly from
`request.query_params`, so `drf-spectacular` can't see it and it's absent
from the generated `api_v1_workspaces_customers_list` operation's query
type. `features/customers/api.ts` narrows this explicitly with a local
`CustomerListQuery` type (`Omit<GeneratedQuery, "ordering"> & { is_active?:
boolean }`) — no `any`, no `ts-ignore`, and a comment pointing at the exact
backend code that makes it real.

### Pagination, search, and filter conventions

List state (`page`, `search`, `status`) lives in the URL query string
(`src/features/customers/url-params.ts`), not component state alone — a
bookmarked/shared `/app/customers?search=jane&status=active` link restores
the same view, and browser back/forward works. Every value read from
`URLSearchParams` is treated as untrusted (a hand-edited or stale link):
`page` must match `^[1-9]\d*$` or falls back to 1, `status` falls back to
`"all"` for anything unrecognized, `search` is length-capped. Defaulted
fields are omitted from the serialized query string, so the URL stays
clean (`/app/customers`, not `/app/customers?page=1&search=&status=all`).
Changing search or status resets `page` to 1; pagination itself preserves
the current search/status. `Pagination` (`components/support/pagination.tsx`)
drives Next/Previous off the backend's actual `next`/`previous` URLs, never
off page-size arithmetic the frontend would have to guess at.

### States

`CustomersListPage`/`CustomerDetailPage` distinguish: initial loading
(skeleton), a network/server error (`ListError` — an `Alert` plus Retry,
never collapsed into "empty"), a confirmed empty result set (two distinct
messages depending on whether a filter is active), and success. Detail
additionally distinguishes a confirmed 404 (`EntityNotFound` — deliberately
generic wording, since the backend returns the identical 404 for "doesn't
exist" and "exists in a different workspace") from a malformed route ID
(validated client-side against a UUID pattern *before* any request is
made — `customer-detail-page.test.tsx` asserts no network call happens for
a non-UUID `customerId`) and from a genuine network error. The
zero-workspace/workspace-load-error/loading states are already handled
once, globally, by `AppShell`'s `WorkspaceGate` (Phase 18) — the customers
pages don't duplicate them.

### Navigation

"Customers" was added to `NAV_ITEMS` (`components/shell/nav-config.ts`) in
Chunk 1 once `/app/customers` became a real route with real data. Chunk 2
adds "Inbox" the same way, now that `/app/inbox` is real too. Real
navigation is now Overview → Inbox → Customers; Tickets is **not** added
yet — an unclickable nav entry for a route that doesn't exist yet is worse
than a short sidebar. `NavLinks`' active-route matching
(`components/shell/nav-links.tsx`) treats every non-`/app` destination as
active for its own path *and* any nested route under it (`startsWith`), so
the sidebar stays highlighted while drilled into `/app/customers/[id]` or
`/app/inbox/[id]`.

### Inbox / Conversations + message timeline (Phase 19 Chunk 2)

**Route model**: `/app/inbox` (list) and `/app/inbox/[conversationId]`
(detail) — "Inbox" is the nav label; the route segment is `conversations`'
close relative in spirit but literally `inbox`, chosen up front per the
build prompt's preferred model rather than the `/app/conversations`
alternative. No duplicate route exists for the same data.

**Conversation API contract**:

| Question   | Answer                                                                                                                                                                                                                    |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| List       | `GET /api/v1/workspaces/{workspace_id}/conversations/` — any active member.                                                                                                                                            |
| Detail     | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/` — 404s exactly like a nonexistent conversation for one belonging to a different workspace.                                                    |
| Messages   | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/` — scoped by **both** workspace and conversation (`conversations/selectors.py`): a foreign-workspace conversation ID 404s this endpoint too, not just conversation detail. |
| Pagination | Backend-standard `PageNumberPagination` on both list and message endpoints — `{count, next, previous, results}`, default page size 50.                                                                                  |
| Filters    | `status` (open/pending/closed), `channel` (web/chat/email/sms/api), `unassigned` (boolean) — all real and backend-tested (`conversations/selectors.py conversation_list_for_workspace`). `customer`/`assigned_to` (UUID) filters also exist backend-side but have no UI control in Chunk 2 — an operator-facing customer/assignee *picker* is a materially separate UX investment better scoped with assignment UI itself. |
| Search     | **Not implemented on the backend** for either endpoint — see the schema-gap note below. No search control exists in the UI.                                                                                             |
| Ordering   | Not implemented on the backend (same dead-parameter situation as `search`) — never sent.                                                                                                                                |
| Mutations  | Real and backend-tested (`POST .../messages/` to send, `.../status/`, `.../close/`, `.../reopen/`, `.../assign/`) but **deferred** — see "Deferred: operator reply and status mutations" below.                        |

**Schema gaps (Category A — typing deficiencies, same shape as Chunk 1's
`is_active`/`ordering` findings)**:

1. `status`/`channel`/`unassigned` (conversation list) are real,
   backend-tested filters absent from the generated
   `api_v1_workspaces_conversations_list` operation's query type — narrowed
   explicitly in `features/conversations/api.ts`'s `ConversationListQuery`.
2. `ordering`/`search` appear in the generated schema for **both**
   `conversations_list` and `conversations_messages_list` (global
   filter-backend inference) but neither view configures `ordering_fields`/
   `search_fields`, and neither selector accepts a `search` argument —
   completely dead parameters on the real backend. Never sent.
3. `Conversation.assigned_to` and `Message.sender` are both nested
   `MembershipSummary` fields the generated schema types as non-nullable,
   but the backing foreign keys (`assigned_to`, `sender_membership`) are
   nullable and DRF correctly serializes `null` for an unassigned
   conversation or a non-human-agent message — `drf-spectacular` doesn't
   infer nullability through a nested read-only serializer the way it does
   for a plain scalar. Re-typed in `features/conversations/types.ts`.
4. The generated request body for `POST .../messages/` is typed as
   `Message` (the read-only response shape) rather than the real
   `MessageCreateSerializer` shape (`direction`, `body`, `external_id?`,
   `metadata?`) — the view's `create()` uses a different serializer than
   its class-level `serializer_class`, which `drf-spectacular` can't see
   without an explicit `@extend_schema` override. Not narrowed in this
   chunk since message send is deferred (see below); flagged here for
   whichever chunk implements it.

**Customer identity in the inbox — an architectural limitation, not a
design choice**: the conversation list/detail response includes only
`customer_id` (a UUID), never a name/email summary
(`conversations/serializers.py ConversationSerializer`). Fetching each
row's customer individually to show a name would be a client-side N+1 (up
to 50 extra requests for one page) — explicitly disallowed (see "No client
N+1" below) — and there is no bulk-by-IDs customer endpoint to fetch all of
a page's customers in one request either (`customers/selectors.py
customer_list_for_workspace` only supports a single free-text `search`, not
an `id__in` filter). Chunk 2 therefore links to the customer honestly, by
ID (`Customer #<first 8 chars>` — `features/conversations/components/
customer-ref-link.tsx`), rather than either an N+1 fetch or a fabricated
name. The minimal backend change that would resolve this is adding a
lightweight customer summary (e.g. `customer_display_name`) to
`ConversationSerializer`, mirroring how `assigned_to` is already embedded
— flagged for a human decision, not implemented here (see "Backend policy").

**No client N+1**: the list page issues exactly one request per
page/filter change — no per-row customer, assignee, or other detail
fetches. Conversation detail issues exactly two requests in parallel (the
conversation itself and its first page of messages — see `queries.ts`'s
`useMessageListQuery` doc comment), never serially chained.

**Message ordering**: the backend orders messages by `(created_at,
sequence)` ascending — oldest first (`conversations/selectors.py
message_list_for_conversation`). `sequence` is a strictly-increasing,
DB-assigned insertion sequence introduced in Phase 16 specifically to
break same-`created_at` ties deterministically (`Message.sequence`'s
backend docstring) — two messages can legitimately share a `created_at`
value (`auto_now_add`'s precision, or a fast burst of sends), and `id`
(a random UUID) is not a safe tie-breaker. The frontend renders `results`
in exactly the order the API returns it and never re-sorts — verified by a
regression test seeding two same-`created_at` messages in a specific order
and asserting the DOM renders them in that same order
(`conversation-detail-page.test.tsx`).

**Sender/source semantics**: `Message.sender_type` (`customer`,
`human_agent`, `ai_agent`, `system`) picks the label; a `human_agent`
message additionally shows the real sender's email
(`message-timeline.tsx`). `direction === "internal"` (a support-only note,
never customer-visible) is marked with a distinct "Internal note" badge and
background tint — a real, backend-enforced distinction
(`MessageCreateSerializer` only allows `outbound`/`internal` from this API;
`internal` is never shown to the customer) that the UI must not blur.
Speaker is never inferred from message body content.

**Message content safety**: rendered as plain text
(`whitespace-pre-wrap break-words`, preserving real newlines and wrapping
long unbroken URLs/words) — no `dangerouslySetInnerHTML`, no custom
HTML/markdown rendering, since the backend returns and stores raw text with
no structured-content contract.

**Timeline semantics**: a plain `<ol>`/`<li>` list, not `role="log"` — the
timeline is a static page load (paginated, not live-updating), so `role="log"`
(an assistive-tech live region) would misrepresent it. Each `<li>` exposes
sender, timestamp, and content together, in reading order.

**Status/channel badges**: semantic text + color via the shared
`EnumBadge` (`components/support/enum-badge.tsx`, new in this chunk) —
never color alone, and a documented **safe fallback for a status/channel
value the frontend doesn't recognize**: the badge falls back to the raw
enum string as its own label and a neutral color rather than crashing or
rendering blank (covered by a dedicated test seeding an unrecognized
future status/channel).

**Deferred: operator reply and status mutations**. The backend genuinely
supports sending a message (`POST .../messages/`, `direction: "outbound" |
"internal"`) and conversation status changes (`.../status/`, `.../close/`,
`.../reopen/`, `.../assign/`) — verified real, not assumed. Both are
deliberately **out of Chunk 2's scope** ("Inbox / Conversations + Message
Timeline" — a read-only viewing experience), consistent with Chunk 1's own
precedent of shipping Customers read-only despite `PATCH` existing. Message
send specifically has a safety wrinkle worth documenting for whichever
chunk implements it: there is no idempotency key or `external_id`
uniqueness constraint on `Message` (unlike `Customer`/`Conversation`, which
do have one), so a naive automatic retry after a network-ambiguous send
could create a real duplicate message — the query client's existing
"mutations never retry" policy (Chunk 1) is necessary but not sufficient
here; a future implementation needs its own explicit ambiguous-failure UI
per the build prompt's Part G, not just "retry: false".

### Tickets + cross-domain operational navigation (Phase 19 Chunk 3)

**Route model**: `/app/tickets` (list) and `/app/tickets/[ticketId]`
(detail) — same pattern as Customers/Inbox. No duplicate route.

**Ticket API contract**:

| Question   | Answer                                                                                                                                                                                                                                                     |
| ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| List       | `GET /api/v1/workspaces/{workspace_id}/tickets/` — any active member.                                                                                                                                                                                       |
| Detail     | `GET /api/v1/workspaces/{workspace_id}/tickets/{ticket_id}/` — 404s exactly like a nonexistent ticket for one belonging to a different workspace.                                                                                                          |
| Create     | `POST .../tickets/` — supported, non-viewer role. Not implemented in this chunk (see "Read-only by design" below).                                                                                                                                          |
| Update     | `PATCH .../tickets/{id}/` — supported (manager+, or the assigned agent). Not implemented.                                                                                                                                                                    |
| Status     | `POST .../{id}/status\|resolve\|reopen/`, assignment via `.../assign/`, `.../unassign/` — all real and backend-tested (`tickets/services.py`). Not implemented — see "Mutation decision" below.                                                            |
| Pagination | Backend-standard `PageNumberPagination` — `{count, next, previous, results}`, default page size 50.                                                                                                                                                         |
| Filters    | `status` (open/in_progress/pending/resolved/closed), `priority` (low/normal/high/urgent), `customer`, `assigned_to`, `unassigned`, `conversation` — all real (`tickets/selectors.py ticket_list_for_workspace`). Only `status`/`priority` have UI selects. |
| Search     | **Not implemented on the backend.** No search control exists in the UI.                                                                                                                                                                                      |
| Ordering   | **Not a client concern**: the backend always sorts by priority (urgent → low) then most-recently-created (`ticket_list_for_workspace`'s `_PRIORITY_ORDER` annotation) — a fixed, deliberate operational order. The generated `ordering` query parameter is a dead global-filter-backend artifact exactly like Customers/Conversations; never sent, and no sort control is offered (a regression test asserts no "sort"/"order" control exists). |
| Customer relation | `customer_id` — always present (a ticket always belongs to a customer). Links to the existing `/app/customers/[customerId]` route.                                                                                                                    |
| Conversation relation | `conversation_id` — nullable (a ticket may be created directly, not from a conversation). When present, links to the existing `/app/inbox/[conversationId]` route.                                                                                    |
| Handoff relation | `HumanHandoff.ticket_id` exists backend-side, but `Ticket` itself carries no handoff/origin field, and `Conversation` exposes neither a ticket nor a handoff field — there is no real "created via handoff" fact surfaceable from the Ticket or Conversation API without a separate Handoff-domain fetch per row (N+1). Omitted; not inferred.                                                                                                     |

**Schema gaps (Category A — typing deficiencies, same shape as prior chunks)**:

1. `status`/`priority`/`customer`/`assigned_to`/`unassigned`/`conversation`
   are real, backend-tested filters absent from the generated
   `api_v1_workspaces_tickets_list` operation's query type (same
   global-filter-backend-inference gap as Customers/Conversations) —
   narrowed explicitly in `features/tickets/api.ts`'s `TicketListQuery`.
2. `ordering`/`search` are dead parameters on the real backend (see table
   above). Never sent.
3. `Ticket.assigned_to` is a nested `MembershipSummary` field the generated
   schema types as non-nullable, but the backing foreign key
   (`Ticket.assigned_to`, `on_delete=SET_NULL`) is nullable — the same
   drf-spectacular nested-nullability gap already documented for
   `Conversation.assigned_to`/`Message.sender`. Re-typed in
   `features/tickets/types.ts`.

**Mutation decision — deferred, consistent with Customers/Conversations**:
status transitions (`resolve`/`reopen`/`status`), assignment, and
create/update are all real, backend-tested capabilities
(`tickets/services.py`), but none are implemented in this chunk. Reasoning,
per mutation:

- **Status/resolve/reopen**: the transition table
  (`TICKET_STATUS_TRANSITIONS`) rejects a same-status transition with a
  clean domain `ValidationError` rather than silently no-op'ing or
  double-recording an audit event — so a blind retry after an ambiguous
  network failure is _individually_ safe (it either succeeds once, or
  surfaces a deterministic "cannot transition from resolved to resolved"
  error on the retry, never a corrupted or duplicated state). Still
  deferred: shipping only status while omitting assignment produces a
  half-interactive, inconsistent surface, and the full required test
  matrix (success / domain-validation error / authorization failure /
  duplicate-submission-blocked / retry-count / invalidation /
  network-ambiguity, per mutation) is a materially separate scope of work
  from this chunk's stated goal ("Tickets + Cross-Domain Operational
  Navigation").
- **Assign/unassign**: `assign_ticket` always records a fresh audit event
  (`TICKET_ASSIGNED`/`TICKET_REASSIGNED`) on every successful call, even a
  no-op reassignment to the same person — so a blind retry after an
  ambiguous failure produces a real duplicate audit-log entry, not just a
  harmless repeated error. Combined with the actor-dependent authorization
  branching (manager+ may reassign anyone; a support agent may only
  self-assign an _unassigned_ ticket), this is the same class of
  "ambiguous side effect" that kept message send deferred in Chunk 2.
- **Create/update**: out of this phase's stated UX scope per the build
  prompt ("this phase primarily needs operational visibility/navigation,
  not a replacement ticket administration system") — human-handoff-created
  ticket creation already exists server-side and needs no client form.

Blind mutation retry: **NO** (the query client's mutation-retry policy from
Chunk 1 remains `retry: 0`; moot here since no mutation is wired up at
all). Read-only is an explicitly sanctioned outcome for this phase, not a
lesser one — see the build prompt's Part G, "Read-only is acceptable."

**Cross-domain operational navigation** — the actual new capability this
chunk adds:

| Link                                   | Real?                                                                                                     | Mechanism                                                                                                          |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ticket → Customer                       | Yes (`Ticket.customer_id`, always present)                                                                | Shared `components/support/customer-ref-link.tsx`, linking to `/app/customers/[customerId]`.                       |
| Ticket → Conversation                   | Yes, when `conversation_id` is non-null                                                                   | "View originating conversation" link to `/app/inbox/[conversationId]`.                                             |
| Conversation → Customer                 | Yes (unchanged from Chunk 2)                                                                              | Same shared `CustomerRefLink`.                                                                                     |
| Conversation → Ticket                   | **N/A — not real.** `ConversationSerializer` exposes no ticket/handoff field.                              | Omitted; not inferred (build prompt Part F §19: "If not directly exposed, do not infer it").                       |
| Customer → related Conversations        | Yes — a real `customer` filter on the conversation list (`conversation_list_for_workspace`)               | `RelatedConversationsPanel` (single bounded query, page 1, on Customer detail) + "View all" link to `/app/inbox?customer=<id>`. |
| Customer → related Tickets              | Yes — a real `customer` filter on the ticket list (`ticket_list_for_workspace`)                            | `RelatedTicketsPanel` (same pattern) + "View all" link to `/app/tickets?customer=<id>`.                             |

`customer` was already a real, backend-tested filter on both the
conversation and ticket list endpoints before this chunk (the Chunk 2
schema-gap note flagged it as "real but unused"); this chunk wires it up
for exactly these two contextual, URL-driven links — **not** a customer
picker in either list UI (`ConversationListParams.customerId` /
`TicketListParams.customerId` are parsed from the URL's `?customer=`
param, validated as a well-formed UUID, and rendered as a dismissible
"Showing tickets/conversations for Customer #…" banner with a "Clear
filter" action — never a dropdown or search box). A URL-supplied customer
ID is not authorization: the backend's own workspace scoping is what
actually enforces access (an ID for a customer in a different workspace
simply yields zero matching rows, never a leak).

**No client N+1**: the Tickets list issues exactly one request per
page/filter change, matching Customers/Conversations. Customer detail now
issues two additional bounded requests (one for `RelatedConversationsPanel`,
one for `RelatedTicketsPanel`) — each a single real, filtered list query for
that one detail page, never a per-row fetch across a list. Ticket detail
issues exactly one request (no related-entity fetch beyond the two real
links above, which cost nothing extra — they're plain `<Link>`s, not
queries).

**Query-key / cache consistency**: `ticketKeys` follows the same
`["workspaces", workspaceId, "tickets", ...]` shape as
`customerKeys`/`conversationKeys` (`features/tickets/query-keys.ts`). A
ticket's embedded `customer_id`/`conversation_id` are plain filter/link
values, never a second cached copy of Customer or Conversation entity
data — `RelatedTicketsPanel`/`RelatedConversationsPanel` call the existing
`useTicketListQuery`/`useConversationListQuery` hooks directly rather than
introducing a parallel "tickets-for-customer" cache shape.

**Status/priority badges**: same `EnumBadge` pattern as Conversations —
semantic text + color, with a documented safe fallback for a status or
priority value the frontend doesn't recognize yet (covered by a dedicated
test seeding an unrecognized future value on both list and detail pages).

**Navigation**: "Tickets" is now the fourth clickable sidebar entry
(`components/shell/nav-config.ts`) — Overview, Inbox, Customers, Tickets.
No Phase 20+ destination (Agents, Approvals, Knowledge, Integrations,
Evaluations) is present.

### Agent Runs + lifecycle visibility (Phase 20 Chunk 1)

**Route model**: `/app/agent-runs` (list) and `/app/agent-runs/[runId]`
(detail) — same pattern as Tickets/Customers/Inbox. No duplicate route.
"Agent Runs" is now the fifth clickable sidebar entry
(`components/shell/nav-config.ts`) — Overview, Inbox, Customers, Tickets,
Agent Runs. No Tool Execution/Approval/Handoff top-level destination exists
yet (Chunks 2-3's job); Tool Executions/Approvals/Handoff, where real, will
live inside Agent Run detail rather than as separate nav items, per the
build prompt's Part E guidance.

**Agent Run API contract**:

| Question | Answer |
| --- | --- |
| List | `GET /api/v1/workspaces/{workspace_id}/agent-runs/` — any active member. |
| Detail | `GET .../agent-runs/{run_id}/` — 404s exactly like a nonexistent run for one belonging to a different workspace (`agents/selectors.py agent_run_get_for_workspace_or_404`). |
| Steps (execution trace) | `GET .../agent-runs/{run_id}/steps/` — safe, structured trace events only (`AgentStepSerializer`); never hidden chain-of-thought. |
| Create | `POST .../agent-runs/` — starts a real run (`CanRunAgents` role, rate-limited). Not implemented — Chunk 1 is visibility-only, no run-triggering UI. |
| Cancel | `POST .../agent-runs/{run_id}/cancel/` — real and backend-tested (`agents/orchestration.py cancel_support_agent_run`), 409 if not cancellable. **Deferred** (see below), not "not supported." |
| Pagination | Backend-standard `PageNumberPagination` — `{count, next, previous, results}`, default page size 50. |
| Filters | `status` (all 8 real enum values) and `agent_id` — both real (`agents/selectors.py agent_run_list_for_workspace`). Only `status` has a UI select; `agent_id` has no picker in Chunk 1 (no Agent Definition management UI exists) but is typed for a future caller. |
| Ordering | Fixed backend order, `-created_at, -id` — no client sort control. |
| Status enum | `pending`, `running`, `succeeded`, `failed`, `cancelled`, `budget_exceeded`, `waiting_for_approval`, `handed_off` (`AgentRunStatusEnum`). |
| Terminal states | `succeeded`, `failed`, `cancelled`, `budget_exceeded`, `handed_off` — mirrored in the frontend as `AGENT_RUN_TERMINAL_STATUSES` (`features/agent-runs/types.ts`), not imported (separate deployables). `pending`/`running`/`waiting_for_approval` are non-terminal. |
| Conversation relation | `conversation_id` — nullable. Links to the existing `/app/inbox/[conversationId]` route when present. |
| Customer relation | **Not real on `AgentRun` itself** — no `customer_id` field exists on the serializer. Not inferred through Conversation (would require a second fetch per row/detail; the build prompt's Part F §55 rule against inferring un-exposed relationships applies the same way it did for Conversation → Ticket in Chunk 3). |
| Ticket relation | `ticket_id` — nullable. Links to the existing `/app/tickets/[ticketId]` route when present. |
| Tool execution relation | Real (`ToolExecution.agent_run` FK), but no `GET` list-by-run endpoint is exposed yet on `tools/urls.py` — Chunk 2's job. Not surfaced here beyond the run's own `tool_call_count` counter. |
| Approval relation | Real (`ApprovalRequest.tool_execution` → `ToolExecution.agent_run`), transitively — no direct run-level approval list endpoint. Chunk 3's job. The run's `waiting_for_approval` status is visible today; the approval record itself is not. |
| Handoff relation | Not surfaced — `AgentRun` carries no handoff FK/field in the current serializer. The `handed_off` terminal status is visible; the underlying `HumanHandoff` record is Chunk 3's job. |
| Permissions | List/detail/steps: any `IsWorkspaceMember`. Create/cancel: `CanRunAgents` (owner/admin/support_manager/support_agent) — irrelevant to this read-only chunk. |

**Schema gap (Category A)**: `status`/`agent_id` are real, backend-tested
list filters absent from the generated `api_v1_workspaces_agent_runs_list`
operation's query type (same global-filter-backend-inference gap as every
prior domain) — narrowed explicitly in `features/agent-runs/api.ts`'s
`AgentRunListQuery`. `ordering`/`search` are dead parameters; never sent.

**Cancellation — explicitly deferred, not "unsupported"**: `POST
.../cancel/` is a real, backend-tested capability. It is not implemented in
Chunk 1 because (a) no other write/mutation pattern exists anywhere in this
frontend yet to build on, and (b) the master prompt's Part F §28 explicitly
sanctions deferring it ("If uncertain: DEFER"). Wiring it up requires the
full required test matrix (duplicate-submission-blocked, `retry: 0`,
terminal/conflict-state handling, invalidation-after-success) that Approve/
Reject in Chunk 3 will need anyway — better built once, consistently, than
half-built here.

**Polling strategy** (`features/agent-runs/queries.ts`): there is no
WebSocket/push channel on this backend for run progress, so a **non-terminal
run's detail and step trace** are polled at a fixed `AGENT_RUN_POLL_INTERVAL_MS`
(5000ms) via TanStack Query's `refetchInterval`, which re-evaluates against
the *latest fetched status* on every scheduling decision — so polling stops
on the very next check once a run turns terminal, not one cycle late. The
**list is never polled** — Chunk 1 is a detail-first workflow (an operator
opens one run to watch it); polling every row of a list would be a much
heavier request volume for a lower-value signal. `refetchIntervalInBackground:
false` additionally pauses polling for a backgrounded browser tab. Covered by
`src/tests/features/agent-runs/polling.test.tsx`: a pure-logic test of the
terminal/non-terminal decision function, plus a fake-timer integration test
proving a real component stops issuing detail requests once the backend
reports a terminal status.

**No client N+1**: the Agent Runs list issues exactly one request per
page/filter change. Run detail issues exactly two requests (the run itself,
and its step trace) — no per-step or per-tool-execution fetch.

**Query-key / cache consistency**: `agentRunKeys` follows the same
`["workspaces", workspaceId, "agent-runs", ...]` shape as every other
domain (`features/agent-runs/query-keys.ts`), with a dedicated `steps(...)`
leaf nested under `detail(...)` so a run's step-trace cache entry is
disjoint per workspace and per run, exactly like every other key.

**Untrusted payload handling**: `AgentStep.safe_metadata` (JSON) is rendered
via a bounded, independently `overflow-auto` `<pre>` block — plain text via
`JSON.stringify`, never `dangerouslySetInnerHTML` — so it can never force
page-level horizontal overflow or be interpreted as markup, per the build
prompt's Part C §16-18.

**Deferred to later Phase 20 chunks** (explicitly, not silently): Tool
Execution detail UI, Approval list/detail + Approve/Reject, Human Handoff
visibility, run cancellation, and any top-level nav destination for those
domains.

### Tool Executions + Execution Trace (Phase 20 Chunk 2)

**Architecture decision — embedded, not standalone** (build prompt Part I
§26): Tool Executions render inside Agent Run detail, in their own "Tool
executions" card alongside the existing "Agent steps" card — no
`/app/agent-runs/[runId]/tools/[executionId]` or `/app/tool-executions/...`
route exists. The two are deliberately separate sections, not merged into
one interleaved timeline: `AgentStep` and `ToolExecution` share no explicit
join key (a step records `tool_requested`/`tool_execution_*` step *types*,
but never a `tool_execution_id` FK) closer than "both belong to the same
run," so fabricating a merged order would be inventing a relationship the
backend doesn't expose. Both lists preserve their own backend-authoritative
order verbatim (`AgentStep.sequence` ascending; `ToolExecution` list
`-created_at, -id` descending) — never client-sorted.

**Tool Execution API contract**:

| Question | Answer |
| --- | --- |
| List | `GET /api/v1/workspaces/{workspace_id}/tools/tool-executions/` — any active member (`ToolExecutionListView`, no explicit permission override beyond workspace membership). |
| Detail | `GET .../tools/tool-executions/{execution_id}/` — real, but **unused in Chunk 2**: the list, filtered by `agent_run_id`, already returns every field the detail endpoint would (same `ToolExecutionSerializer`), so fetching each row's detail individually would be a pure N+1 with zero additional information. |
| Catalog | `GET /api/v1/workspaces/{workspace_id}/tools/` — code-owned, workspace-independent `ToolDefinition` metadata (same rows for every workspace). Fetched once per Agent Run detail view to attach each execution's real `risk_level`/`side_effect_type`/`display_name` (absent from `ToolExecution` itself). |
| Pagination | Backend-standard `PageNumberPagination`, page size 50. Never paginated client-side in Chunk 2: an `AgentVersion.max_tool_calls` is server-capped at 20 (`agents/serializers.py`), so one run's tool-execution list is provably always a single page. |
| Filters | `status` and `agent_run_id` — both real (`tools/selectors.py tool_execution_list_for_workspace`). Only `agent_run_id` is sent (this chunk has no standalone list UI to offer a `status` picker on). |
| Ordering | Fixed backend order, `-created_at, -id` — rendered exactly as returned. |
| Status enum | `pending`, `running`, `succeeded`, `failed`, `timed_out`, `cancelled`, `waiting_for_approval`, `blocked_by_policy`, `approval_terminated` (`ToolExecutionStatusEnum`). |
| Terminal states | `succeeded`, `failed`, `timed_out`, `cancelled`, `blocked_by_policy`, `approval_terminated` — mirrored as `TOOL_EXECUTION_TERMINAL_STATUSES` (`features/tool-executions/types.ts`), matching `tools/models.py`. |
| Attempts/retries | `attempt_count` — a single integer counter on the one `ToolExecution` row (Phase 6's idempotency model: one logical invocation, not one row per attempt). There is no per-attempt history (timestamp/output per retry) in the persisted schema, so none is fabricated — "Attempts: N" is rendered as exactly that, a count. |
| Idempotency | `idempotency_key` (may be blank — a tool opted out) rendered as a plain field when present. No idempotency *behavior* is exposed or claimed beyond what the field itself says. |
| Side-effect honesty | `ToolDefinition.side_effect_type` (`none`/`read`/`internal_write`/`external_write`/`financial`/`destructive`) is shown via `SideEffectBadge`, straight from the catalog — never a claim of "exactly once." Phase 10's real external-delivery guarantee is at-least-once; nothing in this UI says otherwise. |
| Approval relation | **No direct FK** on `ToolExecution` to an `ApprovalRequest`. A real, read-only approval context is still derivable honestly from `ToolExecution`'s own fields: `status="waiting_for_approval"`/`"blocked_by_policy"` are already fully conveyed by the status badge; `status="approval_terminated"` additionally decodes its real `error_code` (`approval_rejected`/`approval_expired`/`approval_cancelled`, per `tools/models.py`'s `APPROVAL_TERMINATED` docstring) into a specific label via `deriveApprovalContext`. No Approve/Reject action, no link to a not-yet-existing Approval route (Chunk 3). |
| Retry endpoint | Not supported by the public API (no manual retry is exposed to a client) — no Retry Tool action exists, matching the build prompt's Part G default. |
| Redaction | Backend-primary: `arguments_redacted`/`result_redacted` are already redacted server-side before being persisted (`common/redaction.py redact()`, applied in `tools/execution.py`) — sensitive-looking keys (password/secret/token/api_key/authorization/…) are replaced with the literal string `"***REDACTED***"` before the row is ever written. The frontend renders exactly what it receives and never attempts to reconstruct a redacted value; the only frontend-side defense-in-depth is that payloads are never interpreted as markup (see below). |

**Payload safety** (`components/support/structured-payload.tsx`, shared by
`AgentStep.safe_metadata` and both `ToolExecution.arguments_redacted`/
`result_redacted`): every value is `JSON.stringify`'d into a `<pre>` text
node — never `dangerouslySetInnerHTML`, `eval`, or `new Function` — so
HTML/script-looking content (a customer-supplied `<script>...</script>`, a
prompt-injection string) is always inert plain text. A native
`<details>`/`<summary>` disclosure gives correct keyboard/AT semantics for
free (no hand-rolled `aria-expanded`). Bounded presentation: a fixed
`max-h-64 overflow-auto` box so a large/deep value scrolls in place rather
than stretching page layout, plus a defensive hard truncation past 20,000
serialized characters (backend payloads are already size-capped upstream —
this is a last-resort guard). No object key or string value is ever
auto-linked as a URL, and no untrusted object is ever spread into an
application/config object.

**Network pattern** (Agent Run detail, one page):

- Terminal run: 4 requests total, once — run detail, steps, tool-execution
  list (filtered by `agent_run_id`), tool catalog. No further requests.
- Non-terminal run: the same 4 requests initially, then run detail, steps,
  and the tool-execution list each re-fetch every `AGENT_RUN_POLL_INTERVAL_MS`
  (5000ms) while non-terminal — 3 requests per interval, never N (one per
  tool execution). The catalog is never re-fetched (code-owned, static for
  the session; default 30s query staleTime already covers a return visit).
  All polling shares the same non-terminal-run condition — one coherent
  policy, not independent timers — and stops for good on the same poll
  cycle a fetch observes the run reach a terminal status.

**Workspace isolation**: `toolExecutionKeys` follows the same
`["workspaces", workspaceId, "tool-executions", "for-run", runId]` /
`["workspaces", workspaceId, "tools", "catalog"]` shape as every other
domain. No standalone Tool Execution route exists to deep-link into a
foreign workspace's execution directly; the only real access path is
through an Agent Run already scoped to the active workspace (a run ID from
another workspace already resolves to the run-detail not-found state — see
Chunk 1 — so its tool executions are unreachable by construction, not by a
separate check).

**Known schema gap**: `ToolDefinition.status` is generated as
`WebhookEndpointStatusEnum` (`"active" | "disabled"`) rather than a
tool-specific enum name — a drf-spectacular component-naming collision
(two unrelated two-value status enums with identical literal values). The
values are correct; only the generated name is misleading. Re-typed as
`ToolDefinitionStatusValue` in `features/tool-executions/types.ts` so no
calling code ever references the confusing generated name. Not blocking.

**Deferred to Chunk 3**: Approval list/detail, Approve/Reject actions,
Human Handoff visibility, and any top-level nav destination for those
domains. Chunk 2 adds no new route and no new nav entry.

### Approvals + Human Handoff (Phase 20 Chunk 3)

The first Chunk with a sensitive mutation: Approve/Reject a real, pending
`ApprovalRequest`. Human Handoff is read-only this chunk (see below).

**Approval API contract**:

| Question | Answer |
| --- | --- |
| List | `GET /api/v1/workspaces/{workspace_id}/approvals/` — any active member (`ApprovalRequestListView`). Ordered `created_at, id` (pending-first, oldest first) — never client-sorted. |
| Detail | `GET .../approvals/{approval_id}/` — any active member. |
| Approve | `POST .../approvals/{approval_id}/approve/` — the URL is the decision; body is `{comment?: string}` only (`ApprovalDecisionInputSerializer`). No client-suppliable `decision`/`decided_by`/`required_role`. |
| Reject | `POST .../approvals/{approval_id}/reject/` — same shape. |
| Pagination | Backend-standard `PageNumberPagination`, page size 50. |
| Filters | `status`, `required_role`, `tool_key` are all real (`approvals/views.py`); only `status` is surfaced in this chunk's list UI. |
| Statuses | `pending`, `approved`, `rejected`, `expired`, `cancelled` (`ApprovalStatusEnum`). Only `pending` is actionable; every other value — including any future one this frontend doesn't recognize — is treated as non-actionable, never assumed decidable (safe fallback, `isActionableApprovalStatus`). |
| Expiry | Server-authoritative: `expires_at` is a real field, but the frontend's clock is never treated as the source of truth for whether a decision will be honored — an already-expired-server-side `pending`-looking row still gets a real 409 from a decide call, handled the same as any other conflict (see "Decision safety" below). |
| Requester/decider identity | `requested_by`/`decision.decided_by` are raw `accounts.User` numeric IDs — no membership/email expansion exists on either serializer. Rendered honestly as `User #<id>`, never resolved to a name/email the API doesn't provide (no guessing via a separate broad members query). |
| AgentRun / ToolExecution / Conversation relation | **None.** `ApprovalRequestSerializer` exposes no `tool_execution_id`, `agent_run_id`, or `conversation_id` field at all (verified directly against the real serializer before building this UI) — only `safe_context` (an opaque JSON blob with `tool_key`/`tool_display_name`/`risk_level`/`side_effect_type`/`policy_reason`/`arguments`). This is why Approval detail carries no "View run"/"View execution" link, and why AgentRun/ToolExecution detail (Chunk 1/2) carry no "pending approval" section — no real, filtered join exists in either direction (master prompt Part H, "no relationship inference"). |
| Frozen action | `safe_context` is the frozen, already-redacted context the decision is made against — rendered read-only via the shared `StructuredPayload` viewer, never re-derived from the gated action's *current* state. |
| Audit | Every decision emits a real `AuditAction.APPROVAL_APPROVED`/`APPROVAL_REJECTED` event server-side (`approvals/services.py decide_approval`) — not surfaced in any UI here (no Audit UI exists), but real and verifiable via a direct DB check. |

**Decision safety** (master prompt Part B, the reason this is the first
Chunk with mutations):

- **No blind retry.** `useDecideApprovalMutation` sets `retry: 0` explicitly
  (TanStack Query v5's own mutation default is already 0 — asserted here,
  not just relied on).
- **Duplicate-submit blocked.** Both Approve and Reject are disabled the
  instant a decision is in flight (`mutation.isPending`), reset only by the
  mutation settling — never optimistically re-enabled before the server
  responds.
- **No optimistic state.** The UI never marks "Approved"/"Rejected" before
  the server confirms; on success, the server's *returned* row replaces the
  cached detail directly (`setQueryData`), and the list cache is invalidated
  — never a locally-guessed status.
- **Already-decided / expired / self-approval-forbidden / permission-denied
  conflicts** (backend: `ApprovalAlreadyResolvedError`, `ApprovalExpiredError`,
  `ApprovalSelfApprovalForbiddenError`, `ApprovalPermissionDeniedError`, all
  surfaced as 409/403 with a safe message) are handled uniformly: the
  mutation's `onError` refetches the approval detail, so the real, current
  server state — not a guess — always redraws the page. The failed
  attempt's safe message is also shown inline, verbatim, never swallowed.
- **Consequence honesty.** A successful decision never claims "Action
  executed successfully" — Approve only means the decision was accepted;
  the gated action may still resume asynchronously. The UI says exactly
  that ("...may still be completing asynchronously") rather than implying
  completion.
- **Concurrent decisions converge.** Proven end-to-end (`e2e/approvals.spec.ts`):
  two real sessions racing Approve vs. Reject on the same request always
  converge to the same single, real, server-persisted outcome — enforced by
  the backend's `select_for_update` + one-decision-per-request DB constraint
  (`approvals/models.py`), never a frontend-side lock.

**Permission model**: Approval authority is a linear escalation
(`support_manager` < `admin` < `owner`) distinct from the workspace's
general capability RBAC — mirrored client-side as `roleSatisfiesRequirement`
(`features/approvals/types.ts`) purely to decide whether to *show* Approve/
Reject at all, using the caller's own real, already-fetched workspace role
(`useWorkspace().activeWorkspace.role`, from `/auth/me/`) — never inferred
from email/name. The backend remains fully authoritative and re-derives
this from the caller's *current* DB membership on every decide call
regardless of what the UI renders (proven directly: `e2e/approvals.spec.ts`'s
permission-denial case attempts a real decide call as a `support_agent`,
which the backend genuinely rejects).

**Approval routes**: `/app/approvals` (list, defaults to `status=pending`)
and `/app/approvals/[approvalId]` (detail, with Approve/Reject when
actionable and permitted). Both are new top-level nav entries.

**Human Handoff API contract** (read-only this chunk):

| Question | Answer |
| --- | --- |
| List | `GET /api/v1/workspaces/{workspace_id}/handoffs/` — any active member. |
| Detail | `GET .../handoffs/{handoff_id}/` — any active member. |
| Assign / Resolve | Real endpoints exist (`HumanHandoffAssignView`/`HumanHandoffResolveView`, manager-role-gated) but are **not implemented in this chunk** — master prompt Part G explicitly allows read-only-only ("Read-only is acceptable"), and mutating a handoff pulls in a second manager-only RBAC surface this chunk's scope didn't budget for. Documented here, not silently omitted. |
| Statuses | `pending`, `assigned`, `resolved`, `cancelled`. |
| Conversation / AgentRun / Ticket relation | **Real** — `HumanHandoffSerializer` exposes `conversation_id`, `agent_run_id` (nullable), `ticket_id` (nullable) directly, unlike `ApprovalRequest`. Every real relation gets a real link; a null one gets an honest "— (not tied to a …)" note, never a guessed link. |
| Filters | `status` and `conversation` are both real (`tickets/selectors.py handoff_list_for_workspace`) — notably **not** `agent_run`, which is why AgentRun detail carries no "related handoff" section (no real filtered join exists for that direction either). |

**Placement**: a standalone `/app/handoffs` + `/app/handoffs/[handoffId]`
route (justified — `HumanHandoffListView` is a real, filterable, paginated
operational queue, the same shape as Approvals) **and** a compact "Human
handoff" section embedded in Conversation detail (`/app/inbox/[id]`), using
the real `conversation` filter — never a guessed join. A conversation may
have at most one *active* handoff at a time
(`handoff_one_active_per_conversation`), but the section renders whatever
real rows the filter returns (including a resolved, non-active one), never
hard-codes "only the active one."

**Security/redaction**: Handoff carries only `safe_summary` (a bounded,
pre-written string) and structured status/reason fields — no raw model
reasoning, no arbitrary payload rendering needed here (unlike Approval's
`safe_context`, which reuses the same `StructuredPayload` safe-viewer as
Chunk 2's redacted tool payloads).

**Backend defect discovered in Chunk 3, fixed in Chunk 3A** (real,
pre-existing, cross-cutting): every view that raised a plain
`django.http.Http404` (essentially every "get one resource or 404" selector
across the whole backend — `agents/selectors.py`, `approvals/views.py`,
`tickets/selectors.py`, etc.) used to get mis-coded by
`common/exceptions.py`'s `custom_exception_handler` as
`{"error": {"code": "validation_error", ...}}` instead of `"not_found"`,
even though the real HTTP status was a genuine 404. Root cause: DRF's own
`exception_handler` converts `Http404` → `NotFound` _inside its own call
frame_; the outer `custom_exception_handler(exc, context)` still saw the
original, un-converted `Http404` when it computed the stable error code, so
`_stable_code_for(exc)`'s `isinstance(exc, NotFound)` check never matched.
**Fixed** (Chunk 3A, `common/exceptions.py`): `_stable_code_for` now maps
`django.http.Http404` directly to `"not_found"`, alongside DRF's own
`NotFound`. Canonical invariant going forward: **HTTP 404 always implies
`error.code === "not_found"`**, for every domain. `ApprovalDetailPage`/
`HandoffDetailPage` were realigned from their Chunk 3 `error.status === 404`
workaround to the same `error.code === "not_found"` check already used by
`AgentRunDetailPage`, `ConversationDetailPage`, `TicketDetailPage`, and
`CustomerDetailPage` — one consistent not-found pattern across every detail
page. See defect `P20-404-01`.

### Knowledge / RAG management (Phase 21 Chunk 1)

Read-only foundation over the real, already-built backend Knowledge/RAG
domain (`backend/knowledge/`). Two real, independent, workspace-scoped
entities — `KnowledgeSource` and `KnowledgeDocument` — are exposed; nothing
about retrieval architecture, ingestion internals, or vector search was
redesigned or invented for the frontend.

**Public API contract discovered** (verified against `knowledge/views.py`,
`knowledge/selectors.py`, `knowledge/serializers.py`, and
`knowledge/tests/test_views.py` — never inferred from models/services
alone):

| Capability | Status |
| --- | --- |
| Document list/detail | **Real**, implemented this chunk. `GET .../knowledge/documents/`, `GET .../knowledge/documents/{id}/`. |
| Source list/detail | **Real**, implemented this chunk. `GET .../knowledge/sources/`, `GET .../knowledge/sources/{id}/`. |
| Upload | Real endpoint (`POST .../documents/`, multipart, `KnowledgeDocumentListCreateView.create`) — **not implemented this chunk** (Chunk 2). |
| Ingestion / retry | Real (`POST .../documents/{id}/retry/`, `GET .../ingestion-jobs/{id}/`) — **not implemented this chunk** (Chunk 2). Not read either: a document's own `status`/`last_ingested_at`/`last_error_code`/`chunk_count` fields already carry every ingestion signal this chunk needs, and there is no field linking a document to its ingestion job IDs, so reading one would mean guessing an ID or an N+1 pattern — both avoided. |
| Retrieval / search | Real (`POST .../search/`, `GET .../retrieval-events/{id}/`) — **not implemented this chunk** (Chunk 3). |
| Delete / archive | **Not a real endpoint at all.** No delete/archive view exists in `knowledge/urls.py` — `KnowledgeSource`/`KnowledgeDocument` only expose `is_active` as a field; there is no way to delete either through the public API. Never invented. |
| Chunk API | **Not a real endpoint at all.** `KnowledgeChunk` is a real model but has no dedicated view — chunk text is only ever visible embedded in a search/retrieval-event response (Chunk 3 territory). |

**Document filters** (`knowledge/selectors.py document_list_for_workspace`):
real filters are `source_id` and `status` — **not** `search`, which the
generated OpenAPI schema types anyway (Category A schema gap, same shape as
every other domain — see `features/handoffs/api.ts`). `ordering` is
schema-only/dead for both documents and sources: neither view sets DRF's
`ordering_fields`, so both always order `-created_at, -id` regardless of any
`ordering` query param.

**Source filters** (`source_list_for_workspace`): `search` (name/description,
case-insensitive `icontains`) and `is_active` are both real; `is_active`
isn't typed in the generated schema at all.

**Statuses**: `KnowledgeDocument.status` — `pending`, `queued`, `processing`,
`ready`, `failed` (`KnowledgeDocumentStatusEnum`). `ready`/`failed` are
terminal (`isTerminalDocumentStatus`); the detail page labels a document
"Settled" or "Still in progress" from this, **never** a percentage or ETA
(no real progress signal exists — master prompt Part A §10). An unrecognized
future status renders safely via the shared `EnumBadge` fallback, same as
every other domain.

**Routes**: one canonical route family, `/app/knowledge` (list) and
`/app/knowledge/[documentId]` (detail) — `KnowledgeDocument` is the entity
operators actually care about (what the RAG pipeline retrieves from).
`KnowledgeSource` has no dedicated detail route this chunk: it's surfaced as
a second read-only tab (`?tab=sources`) on the same list page and as a
plain-text field (never a fake link to a route that doesn't exist) on
Document detail, keeping the route surface to the two entities the master
prompt's preferred shape names rather than adding a third alias.

**Server state**: `["workspaces", wsId, "knowledge", "documents"|"sources", "list"|"detail", ...]`
query keys (`features/knowledge/query-keys.ts`) — same workspace-first
policy as every other domain. A single bounded (`page_size=500`) "all
sources" fetch backs the Documents list's Source filter dropdown — never a
per-document source lookup (master prompt Part G §33's N+1 prohibition).

**Content safety**: `KnowledgeSource`/`KnowledgeDocument` carry no full
document text or chunk content at all — only metadata (`title`,
`original_filename`, `metadata` JSON, `last_error_message_safe`, etc.).
`metadata` is rendered through the existing shared `StructuredPayload`
viewer (`JSON.stringify` into a `<pre>`, never `dangerouslySetInnerHTML`) —
proven both in a unit test and the real-backend E2E smoke with genuine
HTML/script-looking metadata content that renders as inert text.

**Known Phase 21 schema gaps** (none blocking):

| Endpoint | Gap | Blocking? |
| --- | --- | --- |
| `documents_list` | Generated schema types `search`/`ordering`; real filters are `source_id`/`status`, untyped. | No — narrowed locally in `features/knowledge/api.ts`. |
| `sources_list` | Generated schema types `ordering` (dead) but not `is_active` (real). | No — same narrowing. |
| `documents_create` (Chunk 2) | Generated 201 response is typed as `KnowledgeDocumentUpload` (the *request* shape) instead of the real `{document, ingestion_job}` body; `file` is typed `string` (openapi-typescript can't express a binary multipart field). | No — explicit, narrow, documented casts in `features/knowledge/api.ts`. |
| `sources_create` (Chunk 2) | Generated 201 response is typed as `KnowledgeSourceWrite` (the *request* shape) instead of the real full `KnowledgeSource` body; `source_type` is typed required despite the backend's real `required=False, default=upload`. | No — same cast pattern; `source_type: "upload"` sent explicitly. |

### Knowledge upload, ingestion, and retry (Phase 21 Chunk 2)

Adds the three real write operations Chunk 1 deliberately left unimplemented,
plus a minimal source-creation flow to unblock upload in a workspace with no
active source yet.

**Write contract discovered** (`knowledge/services.py`,
`knowledge/serializers.py`, `knowledge/views.py`, `knowledge/tests/
test_views.py`):

| Operation | Method/path | Notes |
| --- | --- | --- |
| Upload | `POST .../knowledge/documents/`, `multipart/form-data` | Real fields only: `source_id`, `title`, `file` (`metadata` is real but unused by this chunk's UI). The backend silently discards any other field a client sends (verified: `test_manager_uploads_multipart_and_internal_fields_are_ignored` posts a spoofed `status`/`chunk_count`/`workspace` and asserts they're ignored) — always creates a document with real server-derived `status: "queued"`. |
| Retry | `POST .../knowledge/documents/{id}/retry/`, no body | Only a `failed` document can be retried — any other status is a real 409 `conflict` ("Only failed documents can be retried."). Response is the `KnowledgeIngestionJob`, not the document; the document's own now-`queued` status is refetched, never hand-assembled. |
| Source creation | `POST .../knowledge/sources/` | Real fields `name` (required), `description` (optional) — this chunk sends only those two; `source_type`/`is_active`/`metadata` are left to their real backend defaults. |
| Delete/archive | — | **Not a real endpoint.** No delete/archive view exists in `knowledge/urls.py`; `is_active` is the only lifecycle field either entity exposes. Never invented. |
| Ingestion job detail | `GET .../knowledge/ingestion-jobs/{id}/` | Real and public, but never called by this frontend — see types.ts's doc comment: a document's own status fields already carry every signal the UI needs, and there is no field linking a document to its job ID (so reading one would mean guessing an ID). |

**File constraints** (backend/config/settings.py, `knowledge/ingestion/
validators.py` — mirrored client-side for UX only, never authoritative):
`text/plain` (`.txt`), `text/markdown` (`.md`, `.markdown`),
`application/pdf` (`.pdf`); max 10 MiB. One file per request (the serializer
has no multi-file field). An oversize file is pre-checked and blocked
client-side with an inline message; every other constraint (MIME/extension
mismatch, empty file, malformed PDF, encrypted PDF, page-count limit) is
enforced only by the real backend and surfaced via its safe error message.

**Ambiguous upload failure** (master prompt Part C §13 — the reason this
chunk's upload mutation is more careful than a typical form): the upload
endpoint has no idempotency key, client external ID, or dedupe token of any
kind (verified against `knowledge/services.py upload_document` — a resubmit
always creates a new `KnowledgeDocument` row, and there's no duplicate-
content check). `isAmbiguousUploadError` (`features/knowledge/mutations.ts`)
distinguishes a transport-level failure (`ApiError.code` of `"network_error"`
or `"timeout"` — the request never reached the backend, or a response never
came back) from a confirmed server rejection (validation/permission/
conflict — a response the server definitely sent). Only the former shows
"We couldn't confirm this upload was received" with a **Refresh list**
action; the frontend never auto-resubmits and never claims "upload failed"
when persistence is genuinely unknown.

**Ingestion state machine**: `pending`/`queued`/`processing` (non-terminal),
`ready`/`failed` (terminal) — unchanged from Chunk 1's discovery, reconfirmed
against `knowledge/services.py run_ingestion`/`retry_document`. No real
progress percentage exists anywhere in the contract; none is invented.

**Polling** (`features/knowledge/queries.ts`, same pattern as
`features/agent-runs/queries.ts` `pollWhileNonTerminal`/
`features/approvals/queries.ts`'s approval-detail poll): only the Document
*detail* query polls (`KNOWLEDGE_DOCUMENT_POLL_INTERVAL_MS` = 5000ms), and
only while the fetched document's `status` is non-terminal;
`refetchIntervalInBackground: false` stops it on a hidden tab or unmount.
The Documents *list* is never polled — an operator watching ingestion
progress opens the one document they uploaded/retried, exactly like
AgentRun/Approval before it; a second, list-level poll underneath an
already-polling detail tab would be a compounded request stream for no
additional signal.

**Retry control**: shown on Document detail only when
`isRetryableDocumentStatus(document.status)` (i.e. `failed`) **and**
`canManageKnowledge(role)` — never for `ready`/`processing`/etc, even to a
manager. The mutation is `retry: 0`; a 409 conflict (e.g. another operator
already retried it from a different tab) refetches the document instead of
guessing, so the real, current server state — including the control
disappearing once the document is no longer `failed` — always wins, same
pattern as Approve/Reject.

**Permissions** (`CanManageKnowledge` — owner/admin/support_manager,
reconfirmed unchanged from Chunk 1): `canManageKnowledge(role)`
(`features/knowledge/types.ts`, mirrors the backend set) gates whether
Upload/New source/Retry controls render at all, using the caller's own
real, already-fetched workspace role — the backend remains fully
authoritative and re-derives this from the caller's current DB membership on
every write regardless of what the UI renders (proven directly:
`e2e/knowledge.spec.ts`'s permission test attempts upload as a
`support_agent`, which the backend genuinely rejects).

**Placement**: no new route. "Upload document" (Documents tab) and "New
source" (Sources tab) are inline toggles on the existing `/app/knowledge`
list page, each revealing a form in place — matching the master prompt's
"use existing Knowledge route architecture" instruction rather than adding
an upload-specific page.

**Test-environment note** (`frontend/src/tests/setup.ts`): jsdom's `File`
class and Node's real `fetch` (undici, the actual network layer MSW
intercepts) are different classes from different realms — a real multipart
upload test fails undici's internal type check on the very first attempt.
`globalThis.File` is replaced with Node's own (`node:buffer`) in test setup
so a real end-to-end upload test (`userEvent.upload` → real `FormData` →
MSW-intercepted `fetch`) actually exercises the real request path instead of
only the UI in isolation. This has no effect on production code, which
always runs against a real browser's own `File`.

### Knowledge retrieval / search preview (Phase 21 Chunk 3)

An operator preview of the real retrieval layer — "what chunks would the RAG
system retrieve for this query?" **Retrieval preview is not answer
generation**: there is no chat UI, no prompt playground, no LLM response
preview anywhere in this feature, and no Retrieval History UI (see below).

**Retrieval contract discovered** (`knowledge/views.py
KnowledgeSearchView`, `knowledge/retrieval/services.py search_knowledge`,
`knowledge/serializers.py KnowledgeSearchRequestSerializer`/
`KnowledgeSearchResponseSerializer`):

| Field | Notes |
| --- | --- |
| Method/path | `POST .../knowledge/search/` — a real mutation, not a read: every call persists a real `RetrievalEvent` (+ one `RetrievalHit` per returned result), verified directly against the service, which wraps both writes in `transaction.atomic()`. |
| Request fields | `query` (required, max `KNOWLEDGE_MAX_QUERY_LENGTH` = 2000 chars), `top_k` (optional, real bounds `[1, KNOWLEDGE_MAX_TOP_K]` = `[1, 20]`, default `KNOWLEDGE_DEFAULT_TOP_K` = 5), `minimum_score`, `source_ids`, `document_ids` (all optional). This chunk's UI exposes `query`, `top_k` (a bounded `[3, 5, 10, 20]` select), and a single-source filter only — `minimum_score` and `document_ids` are real but deliberately unexposed (see `features/knowledge/types.ts`'s doc comment on `KnowledgeSearchRequestInput` for why: no product-safe way to offer a document picker without an unbounded fetch, and a raw score-threshold control isn't part of this chunk's minimal scope). |
| Permission | `IsAuthenticated` + workspace membership only (`WorkspaceScopedMixin`/`get_workspace_for_user_or_404`) — **no `CanManageKnowledge` gate**, same as the read-only Documents/Sources tabs. Any active member, including `support_agent`, can search; reconfirmed by a real E2E test (`e2e/knowledge-search.spec.ts`) that a read-only member's search is never rejected. |
| Searchable scope | Only `ready`, active documents under an active source (`document__status=READY, document__is_active=True, document__source__is_active=True` — part of the SQL query itself, never a post-filter). A `pending`/`queued`/`processing`/`failed` document's chunks are never returned, and this is never implied otherwise in the UI. |
| Response fields | `event_id`, `query`, `sufficient_context`, `results[]` (`chunk_id`, `document_id`, `document_title`, `source_id`, `source_name`, `rank`, `score`, `text`, `citation`). The generated OpenAPI types for this endpoint are accurate — no schema-gap cast needed here, unlike Chunk 2's upload/source-create endpoints. |
| Ordering | Backend-authoritative: `queryset.annotate(distance=CosineDistance(...)).order_by("distance", "document_id", "ordinal", "id")[:top_k]`, with `rank` assigned in that same order. The frontend renders `results` in array order and never re-sorts. |
| Rate limit | None (`DEFAULT_THROTTLE_CLASSES: []`, and `KnowledgeSearchView` sets no `throttle_scope`) — a real, current backend fact reported here, not a frontend concern to compensate for. |

**Score semantics** (traced through the actual math, not inferred from the
field name): `score = max(-1.0, min(1.0, 1.0 - cosine_distance))` — this is
**cosine similarity**, not a distance and not a calibrated probability.
Higher is more similar. The UI labels it **"Similarity 0.XX"** (2 decimals)
— never converted to a percentage, never called "confidence" anywhere in
the codebase (both are asserted absent in unit and E2E tests).

**Result presentation** (`features/knowledge/components/
knowledge-search-panel.tsx`): rank, a real Document link
(`/app/knowledge/{document_id}`, the existing detail route — no new page),
source name as **plain text** (there is no Source detail page in this app,
so no dead link is ever created), the chunk text itself, and its citation
(`page_start`/`page_end`/`start_offset`/`end_offset`/`chunk_ordinal`,
rendered via the existing `StructuredPayload` safe-JSON viewer). No fake
"grounding %"/"relevance %"/"citation quality" metric of any kind.

**Chunk content safety**: retrieved chunk text is **untrusted data** — it
may contain HTML-looking, script-looking, prompt-injection-looking, or
URL-looking text, or long strings. It is rendered as a plain React text node
inside a bounded, internally-scrolling box (`max-h-40 overflow-y-auto`, plus
a defensive 4000-character hard truncation, clearly marked "(truncated)")
— never `dangerouslySetInnerHTML`, raw Markdown-to-HTML, `eval`, or `new
Function`, and never auto-linked. Proven both in unit tests (HTML-looking,
script-looking, and prompt-injection-looking fixtures) and in a real E2E
test that ingests such a chunk through the real pipeline and searches for it.

**Server state / cache architecture** (`features/knowledge/queries.ts
useKnowledgeSearchQuery`): deliberately **not** an ordinary `useQuery` keyed
by request content — search is a telemetry-producing POST, not a cacheable
list. The query is `enabled: false` and fires only via an explicit
`refetch()` call from the form's submit handler (never on mount, key change,
window focus, or reconnect — one explicit search: one request), `retry: 0`
(an automatic retry would silently create a second, invisible
`RetrievalEvent`), and keyed by a single **workspace-scoped "current
search" slot** (`knowledgeKeys.retrievalCurrent(workspaceId)`) rather than
one cache entry per distinct query. The submitted request itself is read
from a `useRef` (not React state) inside `queryFn`, so calling `refetch()`
immediately after setting the ref always uses the just-submitted request —
no stale-closure/second-click bug, no `useEffect` needed to "sync" state
into the query.

**Workspace isolation / in-flight switch safety**: two independent
mechanisms, deliberately redundant. (1) `KnowledgeSearchPanel` is mounted
with `key={workspaceId}` (`knowledge-list-page.tsx`) — switching workspaces
fully unmounts the old panel instance (discarding its draft/result state
entirely) and mounts a fresh one, rather than updating props in place. (2)
Independently, the query-key scoping above means even a late-arriving
response from the old workspace's request can only ever resolve into that
workspace's own cache slot — never the new workspace's. Both are proven: a
unit test simulates the real `key` remount mid-flight (a delayed response
resolving after the switch never appears), and a real E2E test performs the
actual browser-level workspace switch after firing a real search.

**No Retrieval History UI**: `RetrievalEvent`/`RetrievalHit` are real,
persisted on every search, and there is a real, public
`GET .../knowledge/retrieval-events/{event_id}/` endpoint — but it is a
single-event-by-id read, not a list, and it returns exactly the same shape
the search response itself already carries. An internal model with a
single-item read endpoint is not a public list capability; this chunk never
calls or links to it, and `event_id` is never surfaced in the UI.

**No-hit / error states**: "No results" (`sufficient_context: false`,
`results: []`) is rendered as a distinct, non-alarming state — never the
same UI as a network/permission/server error, and never shown for a genuine
failure. Proven with a real, deterministic zero-result E2E case: filtering
by a real Source with zero real `KnowledgeChunk` rows (not a fabricated
empty state, not `minimum_score`-induced, since that control isn't exposed
in this chunk's UI).

**Network**: one explicit search submission → exactly one `POST
.../knowledge/search/` request, plus the Source filter's dropdown reusing
the same already-cached Sources query the Documents tab's filter uses (no
duplicate fetch). No per-hit document/source detail request of any kind —
every displayed field comes from the search response itself. No polling.

### Phase 21 final acceptance gate (Chunk 4)

**Real defect found and fixed**: the Documents/Sources/Search tab strip
(`knowledge-list-page.tsx`) used `role="tablist"` around three plain,
URL-navigating `<Link>`s — a genuine `aria-required-children` axe violation
(impact: critical), since the WAI-ARIA Tabs pattern requires a `tablist` to
contain only `role="tab"` children, and this component implements none of
that pattern's other requirements (no roving tabindex, no arrow-key
navigation, no associated `tabpanel`). Fixed by using a `<nav
aria-label="Knowledge views">` landmark instead — the semantically honest
pattern for a set of section-switching navigation links, each already
carrying a correct `aria-current="page"`. This was the only occurrence of
this pattern anywhere in the frontend. axe now reports 0 critical/serious
violations across every scanned Knowledge state (list, tabs, every document
status, upload form, validation/rejection errors, zero-results, search
results, network-error).

**Inactive-Source retrieval semantics** (Chunk 3's Search filter question,
finally adjudicated): `search_knowledge`'s query includes
`document__source__is_active=True` unconditionally — an inactive Source's
chunks are **never** retrievable, through any filter combination, not just
"not offered by this UI." The Search tab's active-sources-only dropdown is
therefore a precise mirror of a real, unconditional backend constraint, not
merely an operator convenience with a gap — no fix was needed.

**Known Phase 21 intentional omissions** (by design, not oversight — see
the Chunk 1-3 sections above for each one's full rationale): no document
delete/archive, no Source edit/delete, no Source detail page, no Retrieval
History UI (a real single-event-by-id endpoint exists but is never
called/linked), ingestion progress is poll-based with no percentage,
`minimum_score`/`document_ids`/multi-Source retrieval filters are real but
unexposed, upload has no dedupe/idempotency key (by real backend design),
duplicate filenames are allowed, and the pre-existing dev-only
`js-yaml`/`@redocly/openapi-core` audit advisory remains untouched
(production dependencies: 0 vulnerabilities throughout).

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

Added in Phase 19 Chunk 1 (`src/tests/features/customers/`,
`src/tests/lib/query/`): the workspace-scoped query-key factory (disjoint
keys per workspace, per-param variation); the query client's retry policy
(retryable vs. definitive `ApiError` codes, the `authentication_failed`
carve-out, mutations never retrying); URL query-string parsing/serialization
(defaults, malformed `page`/`status`/oversized `search` all falling back
safely, round-tripping); the customer API boundary's request shape
(default params send no query string at all; `is_active`/`search`/`page`
sent correctly; the backend-ignored `ordering` param never sent); and the
full page-level matrix for both `CustomersListPage` and
`CustomerDetailPage` — real data rendering, empty vs. network-error
(distinct, both with a working Retry), debounced search (a burst of
keystrokes producing exactly one URL update, not one per keystroke), the
status filter and pagination each preserving the other and resetting page
to 1 where appropriate, a confirmed 404, a customer belonging to a
*different* workspace resolving to the identical safe not-found UI (never
leaking that the ID exists elsewhere), a malformed (non-UUID) route ID
rejected with **zero** network requests, and — the workspace-isolation
regression this chunk cares most about — switching the active workspace
mid-session causing the old workspace's customer to disappear from the DOM
immediately, with the new workspace's data never bridging the two (mocked
via `src/tests/msw/customer-handlers.ts`, a workspace-scoped in-memory
store mirroring the real backend's list/detail/pagination/search/`is_active`
contract and 404 semantics).

Added in Phase 19 Chunk 2 (`src/tests/features/conversations/`): the
conversation query-key factory (disjoint per-workspace keys, message keys
nesting under their conversation's own detail key); URL query-string
parsing/serialization for status/channel/assignment filters (defaults,
malformed input, round-tripping); the conversation/message API boundary's
request shape (default params send no query string; `status`/`channel`/
`unassigned` sent correctly; the backend-dead `search`/`ordering`
parameters never sent on either endpoint); and the full list/detail/
timeline matrix — real data rendering, empty vs. network-error (both with
Retry), status/channel/assignment filters with pagination preserving them,
a confirmed 404, a conversation belonging to a *different* workspace
resolving to the same safe not-found UI, a malformed route ID rejected
with zero network requests, an unrecognized future status/channel value
rendering a safe fallback instead of crashing, the customer cross-link,
long-content wrapping with no `dangerouslySetInnerHTML`, a zero-message
empty state distinct from loading/error, sender/source rendering across
all four `sender_type` values plus the internal-note distinction, the
message-ordering regression (two same-`created_at` messages rendered in
exact server order, never re-sorted), and — the workspace-isolation
regression this chunk cares most about — switching the active workspace
mid-session causing the old workspace's conversation to disappear from the
DOM immediately (mocked via `src/tests/msw/conversation-handlers.ts`,
scoping messages by *both* workspace and conversation like the real
backend does).

Added in Phase 19 Chunk 3 (`src/tests/features/tickets/`): the ticket
query-key factory (disjoint per-workspace and per-customer-filter keys, and
a regression asserting a ticket key never embeds a duplicate
Customer/Conversation entity representation); URL query-string
parsing/serialization for status/priority/customer filters (defaults,
malformed input including a malformed customer ID silently dropped rather
than sent to the backend, round-tripping); the ticket API boundary's
request shape (default params send no query string; `status`/`priority`/
`customer` sent correctly; the backend-dead `search`/`ordering` never
sent); and the full list/detail matrix — real data rendering, empty vs.
network-error (both with Retry), status/priority filters with pagination
preserving them, a regression asserting no sort/order control is offered
(ordering is backend-fixed), a confirmed 404, a ticket belonging to a
*different* workspace resolving to the same safe not-found UI, a malformed
route ID rejected with zero network requests, an unrecognized future
status/priority value rendering a safe fallback, the real Customer and
Conversation cross-links (and the honest "created directly, not from a
conversation" case when `conversation_id` is null), the contextual
customer-filter banner from a real cross-domain link with its Clear-filter
control, and the workspace-isolation regression (switching the active
workspace mid-session causing the old workspace's ticket to disappear from
the DOM immediately). Also extended `src/tests/features/customers/
customer-detail-page.test.tsx` with the new `RelatedTicketsPanel`/
`RelatedConversationsPanel` cases: real preview rows linking to the real
detail routes, the real `?customer=` "View all" links, and a distinct empty
state per panel when the customer has no related records yet.

Added in Phase 20 Chunk 1 (`src/tests/features/agent-runs/`): the agent-run
query-key factory (disjoint per-workspace, per-status-filter, and
per-run-ID `detail`/`steps` keys); URL query-string parsing/serialization
for the status filter (defaults, malformed input, round-tripping); the
agent-run API boundary's request shape (default params send no query
string; `status` sent correctly; the backend-dead `search`/`ordering` never
sent); the full list/detail matrix — real data rendering, empty vs.
network-error (both with Retry), the status filter with pagination
preserving it, a confirmed 404, a run belonging to a *different* workspace
resolving to the same safe not-found UI, a malformed route ID rejected with
zero network requests, an unrecognized future status value rendering a safe
fallback, the real Conversation and Ticket cross-links (and the honest
"not tied to a conversation/ticket" case when either is null), a rendered
failure block for a failed run, and the workspace-isolation regression
(switching the active workspace mid-session causing the old workspace's run
to disappear from the DOM immediately); and a dedicated
`polling.test.tsx` covering the terminal/non-terminal polling decision as
pure logic plus a fake-timer integration test proving a real
`AgentRunDetailPage` stops issuing detail requests the moment the backend
reports a terminal status.

Added in Phase 20 Chunk 2 (`src/tests/features/tool-executions/`,
`src/tests/components/support/structured-payload.test.tsx`): the
tool-execution query-key factory (disjoint per-workspace, per-run, and
catalog keys); the API boundary's real request shape (`agent_run_id` sent,
`search`/`ordering` never sent); `deriveApprovalContext`'s pure decision
logic for every real status/`error_code` combination, including an
unrecognized future `error_code` falling back safely; the shared
`StructuredPayload` viewer (null/empty-object → dash, empty array rendered
as real content, structured object/array/primitive payloads, long-string
wrapping, pathological-length truncation, HTML/script-looking content
proven inert via a real `window` marker check, a redacted placeholder
rendered verbatim, and the native disclosure semantics); and the full
`ToolExecutionList` matrix — empty state, a successful execution with real
catalog-derived risk/side-effect badges, a failed execution's safe error
fields, honest multi-attempt rendering, the read-only
waiting/approval-terminated-with-reason states with no Approve/Reject
control anywhere in the DOM, a redacted argument rendered exactly as sent,
verbatim (never re-sorted) ordering for two same-timestamp executions,
an unrecognized future status value, network-error-with-retry, and a
regression asserting no manual Retry Tool/Run Tool/Execute action exists.
A dedicated `polling.test.tsx` proves the run's *entire* tool-execution
list is polled as one request per interval while non-terminal (never one
request per execution), that polling stops once the owning run turns
terminal, and that the tool catalog is never polled.

Added in Phase 20 Chunk 3 (`src/tests/features/approvals/`,
`src/tests/features/handoffs/`): the approval/handoff query-key factories
(disjoint per-workspace, per-list-params, per-detail-ID, and — for
handoffs — per-conversation-filter keys); `isTerminalApprovalStatus`/
`isActionableApprovalStatus`/`roleSatisfiesRequirement`'s pure decision
logic, including an unrecognized future role/status falling back safely;
the API boundary's real request shapes (`status` sent, `search`/`ordering`
never sent; `approveApproval`/`rejectApproval` POSTing only `{comment}`);
and the full `ApprovalDetailPage` matrix — pending/approved/rejected/
expired/unknown-status rendering, frozen `safe_context` rendered via
`StructuredPayload` (redaction preserved verbatim), a real Approve and a
real Reject each ending with the honest "may still be completing
asynchronously" wording and no lingering controls, duplicate-submit
blocked via a delayed-response mock proving both controls are disabled
mid-flight and a second click is inert, an already-decided 409 conflict
refetching to show the real terminal state (never a catastrophic error),
a backend permission-denial showing the safe message without corrupting
local state, terminal-state fields (outcome/decided-by/comment) for an
already-resolved approval, a confirmed 404, and a foreign-workspace
approval resolving to the same safe not-found UI. A dedicated
`polling.test.tsx` proves the approval detail polls every interval only
while `pending`, picks up another operator's real decision, and stops
polling once terminal. `ApprovalsListPage`/`HandoffsListPage`/
`HandoffDetailPage`/`ConversationHandoffSection` get the same list/detail/
empty/error/workspace-isolation/unknown-status coverage as every other
domain, plus a conversation-scoped test proving only the real
`conversation`-filtered rows render.

## End-to-end tests (`e2e/`, Phase 18 Chunk 4; extended Phase 19 Chunks 1-3, Phase 20 Chunks 1-3)

Playwright (`@playwright/test`), Chromium only — the mandatory acceptance
browser for this phase; Firefox/WebKit weren't added (single-browser
coverage was judged sufficient for a foundation-only phase, not a gap
worth the added CI time). Config: `playwright.config.ts`.

**Runs against the real backend**, not mocks: `e2e/global-setup.ts` shells
out to `manage.py shell` to create two synthetic users (one with two real
workspace memberships — owner + support_agent — one with zero) directly in
the project's Postgres container, and `e2e/global-teardown.ts` deletes them
unconditionally afterward (also self-healing: setup wipes any `e2e-*`/`E2E *`
leftovers from a prior aborted run before creating fresh ones). Extended in
Phase 19 Chunk 1 to also seed real `Customer` rows in each of the two
workspaces (including one inactive customer) — they need no separate
cleanup, since `Customer.workspace` cascade-deletes with the workspace.
Extended again in Chunk 2 with real `Conversation`/`Message` rows: one
assigned, multi-message conversation in Workspace B (covering all four
`sender_type` values and an internal note), one unassigned/closed
conversation in Workspace B (for filter tests), and one conversation in
Workspace A (for isolation/cross-workspace tests) — likewise no separate
cleanup needed, since both cascade-delete with their workspace. Extended
again in Chunk 3 with real `Ticket` rows: one urgent, assigned Workspace B
ticket with a real `conversation_id` (for the Ticket → Conversation link),
one resolved Workspace B ticket created directly with no conversation (for
the status filter and the honest no-conversation case), and one Workspace A
ticket (for isolation/cross-workspace tests) — no separate cleanup needed,
since `Ticket.workspace` also cascade-deletes.
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

**Added in Phase 19 Chunk 1** (`e2e/customers.spec.ts`) — a real-backend
smoke proof for the Customers domain, separate from Chunk 4's own
accessibility/responsive/full-acceptance pass: listing the active
workspace's real customers and opening a detail record; search narrowing
the real result set; a workspace switch swapping the visible customer list
(the old workspace's customer is asserted gone, not just the new one
present); a customer ID from a different workspace deep-linked directly
resolving to the safe not-found UI, never leaking that the record exists
elsewhere; and logout from the customers page.

**Added in Phase 19 Chunk 2** (`e2e/conversations.spec.ts`) — the same kind
of real-backend smoke proof for Inbox/Conversations: listing the active
workspace's real conversations and opening one to see the real message
timeline (including the internal-note distinction); the status and
assignment filters narrowing the real result set; the customer cross-link
opening the real customer detail page; a workspace switch swapping the
visible conversation list (the old workspace's conversation asserted gone);
a conversation ID from a different workspace deep-linked directly
resolving to the safe not-found UI; and logout from the inbox.

**Added in Phase 19 Chunk 3** (`e2e/tickets.spec.ts`) — the same kind of
real-backend smoke proof for Tickets, plus the new cross-domain navigation
graph: listing the active workspace's real tickets, filtering by status,
and opening one to see real fields; the real Ticket → Customer and
Ticket → Conversation navigation; the honest no-conversation case for a
directly-created ticket; Customer detail's real, filtered links to Tickets
and Conversations for that customer (following the "View all" link and
landing on the same contextual, filtered Tickets list); a workspace switch
swapping the visible ticket list; a ticket ID from a different workspace
deep-linked directly resolving to the safe not-found UI; and logout from
Tickets.

**Added in Phase 20 Chunk 1** (`e2e/agent-runs.spec.ts`) — the same kind of
real-backend smoke proof for Agent Runs: listing the active workspace's real
runs (created directly via Django ORM fixtures in `global-setup.ts` —
`AgentDefinition`/`AgentVersion`/`AgentRun`/`AgentStep` rows, deliberately
not through the orchestration service, since that would make real provider
calls) and filtering by status (including a real `running`, non-terminal
row); opening a run to see real fields, its safe execution trace
(`run_started`/`run_completed` steps), and its final response; the real
Agent Run → Conversation and Agent Run → Ticket navigation; the honest
no-conversation/no-ticket case for a manually-triggered run; a workspace
switch swapping the visible run list; a run ID from a different workspace
deep-linked directly resolving to the safe not-found UI, with its response
text asserted absent (never leaked); and logout from Agent Runs.
`AgentRun.agent_version` is `on_delete=PROTECT` (`agents/models.py`), so
`global-teardown.ts` deletes E2E `AgentRun` rows explicitly before the
`Workspace` cascade delete — Django's cascade collector does not resolve a
`PROTECT` FK against a same-transaction cascade on its own.

**Added in Phase 20 Chunk 2** (`e2e/tool-executions.spec.ts`) — the same
kind of real-backend smoke proof for Tool Executions, embedded in Agent Run
detail: a real successful `demo.echo` execution with its catalog-derived
`risk_level`/`side_effect_type` badges and structured JSON result visible
without needing to expand a disclosure (defaults open); a real failed
`demo.flaky` execution's safe error code/message with no
traceback/`File "..."` text anywhere on the page; a real backend-redacted
argument (`***REDACTED***`, from a FAKE seeded secret-shaped value — the
seeded fake secret string itself is asserted absent, proving the actual
backend redaction contract rather than a frontend guess); the real
read-only `waiting_for_approval` status on a non-terminal run with no
Approve/Reject control; a regression asserting no manual
Retry/Run/Execute tool action exists anywhere; and a workspace switch
proving a foreign run's tool executions are never visible (the run itself
already resolves to its own real, empty-for-that-workspace list).
`global-setup.ts` also calls the real, idempotent `sync_tool_definitions()`
(the same call the `seed_demo` management command and data migration make)
to populate the code-owned `ToolDefinition` catalog, then creates real
`ToolBinding`/`ToolExecution` rows directly via the ORM — never through the
execution runtime, which would require a real bounded worker
call. `ToolExecution.tool_binding`/`tool_definition`/`agent_version` are
all `on_delete=PROTECT` too, so `global-teardown.ts` deletes E2E
`ToolExecution` rows before `AgentRun` rows, before the `Workspace` cascade
— the same ordering constraint as Chunk 1's `AgentRun` fix, one level
deeper.

**Added in Phase 20 Chunk 3** (`e2e/approvals.spec.ts`,
`e2e/handoffs.spec.ts`) — the first real-backend acceptance proof of a
sensitive mutation: the real pending queue and a pending approval's frozen,
already-redacted context; a real Approve and a real Reject each verified
to persist across a page reload (not just local state); a genuine
concurrent-decision race between two independent logged-in browser
contexts (Approve vs. Reject on the same request, fired near-simultaneously)
proven to converge to one real, identical, server-persisted outcome in
both tabs; an already-expired approval with no Approve/Reject anywhere; an
already-decided approval rendering its real terminal decision (outcome,
decided-by, comment); a genuine permission denial — a real `support_agent`
membership can view but the backend truly refuses to let it decide, proven
by attempting the real decide call, not just hiding the button; a
foreign-workspace approval deep-link resolving to the same safe not-found
UI; and a regression asserting no manual tool-execution or handoff mutation
control exists anywhere on the Approval screen. The handoff spec proves the
real queue, a resolved handoff's real Ticket link and assignee, the
conversation-embedded handoff section via the real `conversation` filter
(including a resolved, non-active row — proving real data, not an
"active-only" shortcut), workspace isolation, and that no Assign/Resolve
control exists (read-only this chunk). `global-setup.ts` builds real
`ApprovalRequest` rows directly via the ORM — `RiskAssessment`/
`PolicyEvaluation` alongside them, mirroring exactly what
`approvals.services.create_or_reuse_approval_request` persists for a real
`payment.refund` gate (verified empirically against the real serializer
before writing the fixture) — never through the orchestration/policy-gate
path, which would require a live-or-faked payment provider call.
`ApprovalRequest.risk_assessment` is `on_delete=PROTECT` against
`RiskAssessment`, which itself cascades from `ToolExecution` — one level
deeper than Chunk 2's `ToolExecution`-before-`AgentRun` ordering —
so `global-teardown.ts` deletes `ApprovalRequest` (and its cascaded
`ApprovalDecision`) before `ToolExecution`, before `AgentRun`, before the
`Workspace` cascade. The approval fixtures deliberately use dedicated
`AgentRun` rows (`ws_a_approvals_run`/`ws_b_approvals_run`), never
`ws_a_agent_run`/`ws_b_agent_run_running` — reusing either broke Chunk 2's
own "this run has zero tool executions" / "this run has exactly one
waiting-for-approval execution" fixture invariants, caught by Chunk 2's own
E2E spec failing during this chunk's full-suite regression run.

**Real backend defect found via this chunk's own E2E assertions**: the
foreign-workspace-approval not-found case initially failed against the real
backend — not a test bug, but the mis-coded-404 backend defect documented
above ("Approvals + Human Handoff", "Known backend defect discovered this
chunk"). Root-caused by inspecting the real response body (Playwright
response listener, not a mock), confirmed to affect AgentRun's equivalent
route too (masked there only because that route's Http404 message text
happens to overlap the E2E assertion's substring match). Fixed at the
frontend layer only, in this chunk's own new components; no backend file
was modified.

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
