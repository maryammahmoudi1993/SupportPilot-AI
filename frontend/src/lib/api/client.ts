/**
 * Central HTTP/API transport.
 *
 * `apiClient` is the one place that knows the backend's base URL and
 * default fetch behavior. It is generated-type-aware via `openapi-fetch` and
 * `src/types/api.ts` (see scripts/generate-api-types.mjs) — every request
 * path, method, and response shape is checked against the real backend
 * OpenAPI schema at compile time.
 *
 * `credentials: "include"` is required because the backend's refresh-token
 * cookie is HttpOnly and sent by the browser automatically — the frontend
 * never reads or writes it directly (see README.md, "Authentication").
 *
 * Two request middlewares are registered here, both reading from
 * dependency-free stores (token-store.ts, lib/cookies.ts) rather than
 * importing session.ts/csrf.ts, so this module stays a leaf in the auth
 * dependency graph (see README.md, "Auth architecture"):
 *
 * 1. Authorization — attaches `Bearer <access token>` whenever one is held
 *    in memory (token-store.ts). Safe to attach unconditionally, including
 *    to the AllowAny auth endpoints (login/csrf/refresh/logout): none of
 *    them require it, and none reject an extra header.
 * 2. CSRF — attaches `X-CSRFToken` from the `sp_csrftoken` cookie
 *    (backend's `CSRF_COOKIE_NAME`) to every non-safe-method request, per
 *    the backend's explicit `enforce_csrf()` contract (see
 *    backend/common/csrf.py). This only takes effect on requests made
 *    *after* the CSRF cookie has been primed (lib/api/csrf.ts); until then
 *    it's a harmless no-op.
 */
import createClient from "openapi-fetch";

import { config } from "@/lib/config";
import { getCookie } from "@/lib/cookies";
import { getAccessToken } from "@/lib/api/token-store";
import type { paths } from "@/types/api";

/** Default per-request timeout. Long-running or upload endpoints should pass their own. */
export const DEFAULT_TIMEOUT_MS = 15_000;

/** Must match the backend's `CSRF_COOKIE_NAME` (backend/config/settings.py). */
export const CSRF_COOKIE_NAME = "sp_csrftoken";
/** Must match the backend's `CSRF_HEADER_NAME` (`HTTP_X_CSRFTOKEN` → `X-CSRFToken`). */
const CSRF_HEADER_NAME = "X-CSRFToken";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

export const apiClient = createClient<paths>({
  baseUrl: config.apiBaseUrl,
  credentials: "include",
  // Resolve `fetch` dynamically per call rather than capturing
  // `globalThis.fetch` once at client-creation time. Request-mocking tools
  // (MSW, used in this project's tests) patch `globalThis.fetch` — a
  // reference captured before that patch runs (e.g. at module-import time,
  // ahead of a test's `beforeAll`) would silently keep hitting the real
  // network. This also makes the client robust to any environment that
  // installs/replaces `fetch` after module load.
  fetch: (...args) => globalThis.fetch(...args),
});

apiClient.use({
  onRequest({ request }) {
    const token = getAccessToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }

    if (!SAFE_METHODS.has(request.method)) {
      const csrfToken = getCookie(CSRF_COOKIE_NAME);
      if (csrfToken) {
        request.headers.set(CSRF_HEADER_NAME, csrfToken);
      }
    }

    return request;
  },
});
