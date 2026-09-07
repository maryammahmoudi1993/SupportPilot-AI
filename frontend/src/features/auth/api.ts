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
import { unwrap } from "@/lib/api/request";
import { withAccessTokenRetry } from "@/lib/api/session";
import { setAccessToken } from "@/lib/api/token-store";

import type { CurrentUser, LoginCredentials } from "@/features/auth/types";

export async function login(credentials: LoginCredentials): Promise<CurrentUser> {
  await ensureCsrfCookie();
  const body = await unwrap(
    apiClient.POST("/api/v1/auth/login/", {
      body: credentials,
    }),
  );
  setAccessToken(body.access);
  return body.user;
}

/**
 * Best-effort server-side session revocation. Local privileged state is
 * always cleared regardless of whether the server call succeeds — a
 * network outage or an already-expired session must never leave the user
 * stuck looking logged in (see README.md, "Logout").
 */
export async function logout(): Promise<void> {
  try {
    await ensureCsrfCookie();
    await unwrap(apiClient.POST("/api/v1/auth/logout/"));
  } catch {
    // Swallowed intentionally — see the doc comment above.
  } finally {
    setAccessToken(null);
  }
}

/** Protected — goes through the coordinated refresh-and-retry-once flow. */
export function fetchCurrentUser(): Promise<CurrentUser> {
  return withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/"));
}
