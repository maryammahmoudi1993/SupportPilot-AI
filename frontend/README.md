# SupportPilot AI — Frontend

The frontend for SupportPilot AI: a Next.js (App Router) application that
consumes the Django/DRF backend in [`../backend`](../backend). This is the
**Phase 18 foundation** — framework, design system, and typed API transport
only. Authentication, workspace context, protected routing, and the
application shell land in the following chunks/phases; see
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
Query, ...) has been introduced yet. Chunk 1 has no server data fetching to
justify one; the decision for later chunks (workspace context, protected
data views) is deferred to when that need is concrete, per the "don't add a
layer for fashion" principle in the build prompt.

## Directory structure

```
frontend/
  src/
    app/            App Router routes, layouts, and route-level UI states
    components/ui/  Design-system primitives (Button, Input, Card, ...)
    lib/            Framework-agnostic code: API transport, config, utils
      api/           Central HTTP client, error normalization, timeout helper
    types/          Generated types only (api.ts) — never hand-edited
    tests/          Vitest specs, mirroring the src/ layout they cover
  scripts/          One-off Node scripts (API type regeneration)
  openapi.yaml      Generated OpenAPI schema snapshot (see below)
```

Feature domains (customers, conversations, tickets, agents, approvals,
knowledge, integrations, evaluations, settings) get their own directories
under `src/features/` starting in the phase that implements them — Phase 18
intentionally has none yet, to avoid scaffolding empty directories no code
uses.

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

## API transport (`src/lib/api`)

- **`client.ts`** — the one `apiClient` instance (`openapi-fetch`, typed
  against `src/types/api.ts`), bound to `NEXT_PUBLIC_API_BASE_URL`, with
  `credentials: "include"` so the backend's HttpOnly session/CSRF (and later
  refresh-token) cookies are sent automatically. No feature code should
  construct its own `fetch()`/client.
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

No authentication is wired into the transport yet. When Chunk 2 adds it,
token attachment and 401/refresh handling are added as `apiClient.use()`
middleware here — not scattered through feature code — per the build
prompt's "central transport" requirement.

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
rather than a component library — Chunk 1's primitive set doesn't yet need
compound accessibility behavior (a menu, a dialog) that would justify
pulling in Radix. That's the natural point to introduce it, when the app
shell (Chunk 3) needs a workspace switcher / user menu.

## Environment variables

Copy `.env.example` to `.env.local` for local development:

```bash
cp .env.example .env.local
```

| Variable                   | Required | Notes                                                                                                                                                            |
| -------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_BASE_URL` | Yes      | Backend base URL including the version prefix, e.g. `http://localhost:8000/api/v1`. Read and validated (fails fast if missing/malformed) in `src/lib/config.ts`. |

Every variable exposed to the browser is prefixed `NEXT_PUBLIC_`; nothing
else is read from `process.env` in client code. No backend secret is ever
read by, or exposed through, the frontend.

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

## Testing

Vitest + React Testing Library + `jsdom`, configured in
`vitest.config.mts`. Tests live under `src/tests/`, mirroring the directory
they cover (`src/tests/lib/api/errors.test.ts` covers `src/lib/api/errors.ts`,
etc.) rather than living next to source files, so `src/` stays
implementation-only. `src/tests/setup.ts` registers `jest-dom` matchers,
explicit RTL cleanup between tests, and a valid fallback
`NEXT_PUBLIC_API_BASE_URL` so config validation doesn't need per-file
boilerplate.

Chunk 1 coverage: environment config validation (missing/malformed/wrong
protocol), API error normalization (well-formed envelope, unknown error
code, non-envelope body, network failure, timeout), the request-timeout
helper, and the core UI primitives' accessibility semantics (`Button`
disabled/loading state, `Alert`'s `role="alert"` vs `role="status"`).
Authentication, workspace-switching, and route-protection test coverage
lands with those features in later chunks.

## Security notes

- **Token storage**: not yet applicable — Chunk 1 has no authentication.
  When it lands (Chunk 2), the backend's login endpoint returns a JSON
  access token plus a separate HttpOnly refresh cookie set by the server
  (see the generated `src/types/api.ts` — `POST /api/v1/auth/login/`); the
  access token is held in memory only (never `localStorage`/`sessionStorage`),
  and the refresh cookie is never read or written by frontend code — the
  browser sends it automatically because `credentials: "include"` is set on
  every request.
- **CSRF**: the backend issues a CSRF-priming endpoint
  (`GET /api/v1/auth/csrf/`) ahead of state-changing session requests; wiring
  the resulting header into `apiClient` is part of the Chunk 2 auth work, not
  Chunk 1.
- **Frontend authorization**: the frontend never decides what a user is
  allowed to do. Hiding a control based on role/permission is a UX
  convenience only — the backend's own RBAC/tenant-scoping response (403/404)
  is authoritative, and the UI must handle receiving one even when it also
  hid the control.
