/**
 * Central HTTP/API transport.
 *
 * `apiClient` is the one place that knows the backend's base URL and
 * default fetch behavior. It is generated-type-aware via `openapi-fetch` and
 * `src/types/api.ts` (see scripts/generate-api-types.mjs) — every request
 * path, method, and response shape is checked against the real backend
 * OpenAPI schema at compile time.
 *
 * `credentials: "include"` is required because the backend's session/CSRF
 * cookies (and, from Phase 19 on, the refresh-token cookie) are HttpOnly and
 * sent by the browser automatically — the frontend never reads or stores
 * them directly (see README.md, "Security notes").
 *
 * No authentication headers or CSRF token attachment are wired in yet:
 * Phase 18 Chunk 1 is transport-only. That lands with the auth provider in
 * Chunk 2, as a `client.use()` middleware here — not scattered through
 * feature code.
 */
import createClient from "openapi-fetch";

import { config } from "@/lib/config";
import type { paths } from "@/types/api";

/** Default per-request timeout. Long-running or upload endpoints should pass their own. */
export const DEFAULT_TIMEOUT_MS = 15_000;

export const apiClient = createClient<paths>({
  baseUrl: config.apiBaseUrl,
  credentials: "include",
});
