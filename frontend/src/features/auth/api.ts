/**
 * The three auth-domain operations: login, logout, and fetching the current
 * user. Each talks to `apiClient` directly (not through
 * `session.withAccessTokenRetry`) — that's what structurally guarantees
 * none of them can recurse into the refresh flow: login/logout 401s are
 * terminal (bad credentials / already-logged-out), not "go refresh and
 * retry", and refresh itself lives in session.ts, one level below this.
 */
import { apiClient } from "@/lib/api/client";
import { ensureCsrfCookie } from "@/lib/api/csrf";
import { clearLogoutPending, markLogoutPending } from "@/lib/api/logout-intent";
import { requestWithTimeout, withRequestTimeout } from "@/lib/api/request";
import { withAccessTokenRetry } from "@/lib/api/session";
import { setAccessToken } from "@/lib/api/token-store";

import type { CurrentUser, LoginCredentials } from "@/features/auth/types";

/**
 * Every request here is bounded by `requestWithTimeout` (`lib/api/request.ts`)
 * — a hung login/logout/`/me/` request must never leave the UI stuck
 * indefinitely (a permanently-disabled submit button, an infinite spinner)
 * just because the server never responds (see frontend/README.md, "Auth
 * request timeout policy").
 */
export async function login(credentials: LoginCredentials): Promise<CurrentUser> {
  await ensureCsrfCookie();
  const body = await requestWithTimeout((signal) =>
    apiClient.POST("/api/v1/auth/login/", {
      body: credentials,
      signal,
    }),
  );
  setAccessToken(body.access);
  // A fresh login supersedes any earlier unconfirmed logout: the old
  // refresh cookie this login replaces is exactly what that logout wanted
  // revoked, so there's nothing left to warn about.
  clearLogoutPending();
  return body.user;
}

/**
 * "complete" — the backend confirmed the refresh token was revoked.
 * "server_unconfirmed" — the local session was still cleared (see below),
 * but the request to revoke it server-side failed, so the refresh cookie
 * may still be valid until it naturally expires or a later attempt
 * succeeds. Never reported to the user as "you are fully signed out" —
 * see LoginForm's handling of `AuthState.logoutPending`.
 */
export type LogoutResult = "complete" | "server_unconfirmed";

/**
 * Local privileged state is always cleared immediately, before the network
 * call even starts — a network outage or an already-expired session must
 * never leave the user looking logged in (see README.md, "Logout"). Server
 * revocation is still attempted and its result reported via the return
 * value, rather than silently swallowed: the caller needs to know whether
 * it can honestly claim the session is fully gone.
 */
export async function logout(): Promise<LogoutResult> {
  setAccessToken(null);
  try {
    await ensureCsrfCookie();
    await requestWithTimeout((signal) => apiClient.POST("/api/v1/auth/logout/", { signal }));
    clearLogoutPending();
    return "complete";
  } catch {
    // A timeout lands here exactly like a network failure or a real server
    // error: local state is already cleared (above, before any await), the
    // server call's outcome is unknown, and that's precisely what
    // "server_unconfirmed" means — no indefinite wait, and no separate
    // timeout-specific branch needed.
    markLogoutPending();
    return "server_unconfirmed";
  }
}

/**
 * Protected — goes through the coordinated refresh-and-retry-once flow.
 * `withAccessTokenRetry` owns the `unwrap()` call (it needs the raw
 * `{data,error,response}` shape to detect a 401 and retry), so this uses
 * `withRequestTimeout` — the bounding half of `requestWithTimeout` without
 * the unwrapping — rather than double-unwrapping. `callFactory` is invoked
 * up to twice by `withAccessTokenRetry` (once, then once more after a
 * refresh); each invocation gets its own bounded timeout window, not one
 * shared budget across both attempts.
 */
export function fetchCurrentUser(): Promise<CurrentUser> {
  return withAccessTokenRetry(() =>
    withRequestTimeout((signal) => apiClient.GET("/api/v1/auth/me/", { signal })),
  );
}
