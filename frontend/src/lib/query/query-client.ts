/**
 * Server-state client factory.
 *
 * Phase 19 is the first phase with enough workspace-scoped server state
 * (multiple lists, detail pages, pagination, cross-domain navigation) to
 * justify a real cache — see frontend/README.md, "Server-state strategy",
 * for why TanStack Query and why now.
 *
 * Retry policy (deliberate, not the library default):
 * - transport failures (`network_error`, `timeout`) and `internal_server_error`
 *   are the only retryable outcomes — genuinely transient, worth a bounded
 *   retry.
 * - every other `ApiError` code (`validation_error`, `permission_denied`,
 *   `not_found`, `conflict`, `rate_limited`, `invalid_request`,
 *   `parse_error`, `unknown_error`) is a definitive outcome and is never
 *   retried here.
 * - `authentication_failed` is explicitly excluded from retry: a 401 that
 *   reaches this layer already survived `session.ts`'s own
 *   refresh-and-retry-once (see lib/api/session.ts) — retrying it again here
 *   would just race that mechanism. A definitive 401 is handled by
 *   AuthProvider's session-expired handler (see features/auth/auth-provider.tsx),
 *   not by query retries.
 * - mutations never retry blindly (`retry: false`) — see frontend/README.md,
 *   "Mutation retry policy", for why an ambiguous retry is worse than a
 *   surfaced error for state-changing requests.
 */
import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/lib/api/errors";

const MAX_QUERY_RETRIES = 2;

/**
 * Bounded, fast backoff — 200ms, then 400ms — rather than the library
 * default (`1000 * 2^attempt`, up to 30s). Two retries at library defaults
 * would leave an operator staring at a spinner for up to 3 extra seconds
 * over a single transient failure; this still gives a genuinely transient
 * blip a moment to clear without making "retry, then give up" feel broken.
 */
function queryRetryDelay(attempt: number): number {
  return Math.min(200 * 2 ** attempt, 1000);
}

const RETRYABLE_CODES = new Set<ApiError["code"]>([
  "network_error",
  "timeout",
  "internal_server_error",
]);

function isRetryableError(error: unknown): boolean {
  // Every failure that reaches a query's `error` is already normalized to
  // an `ApiError` (see lib/api/request.ts's `unwrap`) — a non-`ApiError`
  // here would be unexpected, and the safe default for the unexpected case
  // is "don't retry", not "retry blindly".
  if (!(error instanceof ApiError)) {
    return false;
  }
  return RETRYABLE_CODES.has(error.code);
}

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  return failureCount < MAX_QUERY_RETRIES && isRetryableError(error);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetryQuery,
        retryDelay: queryRetryDelay,
        // Refetch-on-focus/reconnect defaults fight determinism in tests
        // and don't add real value for an operator workspace that already
        // has explicit retry affordances everywhere — an operator asks for
        // fresh data by navigating or hitting Retry, not by an implicit
        // background refetch.
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        staleTime: 30_000,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
