/**
 * CSRF cookie priming.
 *
 * The backend's login/refresh/logout endpoints authenticate via a cookie
 * (refresh token) rather than the JWT `Authorization` header, so DRF's
 * automatic CSRF exemption for token auth doesn't apply — they explicitly
 * call `enforce_csrf()` (backend/common/csrf.py) and require Django's
 * standard double-submit cookie: an `X-CSRFToken` header matching the
 * `sp_csrftoken` cookie value. client.ts's request middleware attaches that
 * header automatically once the cookie exists; this module is what makes
 * sure it exists before the first state-changing auth request.
 */
import { apiClient, CSRF_COOKIE_NAME } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { unwrap } from "@/lib/api/request";
import { assertCsrfHostnameCompatible } from "@/lib/api/topology";
import { getCookie } from "@/lib/cookies";

/**
 * Ensure the CSRF cookie is present, priming it via `GET /auth/csrf/` if
 * not. Safe to call before every login/refresh/logout request — a no-op
 * network-wise once the cookie already exists.
 */
export async function ensureCsrfCookie(): Promise<string> {
  assertCsrfHostnameCompatible();

  const existing = getCookie(CSRF_COOKIE_NAME);
  if (existing) {
    return existing;
  }

  await unwrap(apiClient.GET("/api/v1/auth/csrf/"));

  const primed = getCookie(CSRF_COOKIE_NAME);
  if (!primed) {
    throw new ApiError(
      "Unable to establish a secure session. Check that cookies are enabled in your browser.",
      { code: "unknown_error", status: null },
    );
  }
  return primed;
}
