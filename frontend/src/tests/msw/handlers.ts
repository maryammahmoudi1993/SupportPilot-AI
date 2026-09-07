/**
 * Request-level mocks matching the real backend contract (accounts/views.py,
 * accounts/serializers.py, common/exceptions.py) — status codes, the
 * `{error:{code,message,details?}}` envelope, and the login/refresh/logout
 * CSRF requirement all mirror the actual API.
 *
 * One deliberate simplification: Node's `fetch` (undici) doesn't wire a
 * mocked response's `Set-Cookie` header into jsdom's `document.cookie` the
 * way a real browser would — there is no browser-style cookie jar bridging
 * the two. The CSRF cookie (JS-readable in real life too) is set for real
 * via `document.cookie` in the `/csrf/` handler below, so `src/lib/api/csrf.ts`
 * is exercised unmodified. The refresh-token cookie is HttpOnly — no
 * frontend code ever reads it in real life either — so its
 * presence/validity is tracked here as private mock state instead
 * (`refreshCookieValid`), which is the accurate abstraction: from the
 * frontend's point of view that cookie is opaque either way.
 */
import { HttpResponse, http } from "msw";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const CSRF_COOKIE_NAME = "sp_csrftoken";
const CSRF_HEADER_NAME = "x-csrftoken"; // MSW lower-cases header lookups

export const FIXTURE_USER = {
  id: 42,
  email: "jane@example.com",
  password: "correct-horse-battery-staple",
  display_name: "Jane Doe",
  workspaces: [] as unknown[],
};

/** Mutable mock server state, reset between tests via `resetAuthMockState()`. */
export const mockState = {
  refreshCookieValid: false,
  currentAccessToken: null as string | null,
  refreshCallCount: 0,
  loginCallCount: 0,
  meCallCount: 0,
  /** When set, /me/ (and thus withAccessTokenRetry) rejects every access token, forcing a refresh. Cleared automatically on a successful refresh, simulating ordinary token expiry. */
  forceMeUnauthorized: false,
  /** When set, /me/ rejects every access token permanently — NOT cleared by a successful refresh. Simulates a user deactivated mid-session: refresh succeeds, but the resource is still forbidden. */
  meAlwaysUnauthorized: false,
  /** When set, /refresh/ fails regardless of cookie state (simulates network outage vs invalid session). */
  refreshNetworkError: false,
  /** When set, /login/ always 429s (rate-limit simulation). */
  loginRateLimited: false,
  /** When set, /login/ simulates a network failure (no response at all). */
  loginNetworkError: false,
};

export function resetAuthMockState(): void {
  mockState.refreshCookieValid = false;
  mockState.currentAccessToken = null;
  mockState.refreshCallCount = 0;
  mockState.loginCallCount = 0;
  mockState.meCallCount = 0;
  mockState.forceMeUnauthorized = false;
  mockState.meAlwaysUnauthorized = false;
  mockState.refreshNetworkError = false;
  mockState.loginRateLimited = false;
  mockState.loginNetworkError = false;
  document.cookie = `${CSRF_COOKIE_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
}

let csrfCounter = 0;

function requireCsrf(request: Request): HttpResponse<{ error: unknown }> | null {
  const header = request.headers.get(CSRF_HEADER_NAME);
  const cookieMatch = document.cookie.match(new RegExp(`${CSRF_COOKIE_NAME}=([^;]*)`));
  const cookieValue = cookieMatch?.[1];
  if (!header || !cookieValue || header !== cookieValue) {
    return HttpResponse.json(
      { error: { code: "permission_denied", message: "CSRF validation failed." } },
      { status: 403 },
    );
  }
  return null;
}

function issueAccessToken(): string {
  const token = `mock-access-token-${++csrfCounter}`;
  mockState.currentAccessToken = token;
  return token;
}

export const authHandlers = [
  http.get(`${BASE}/api/v1/auth/csrf/`, () => {
    const token = `mock-csrf-token-${++csrfCounter}`;
    document.cookie = `${CSRF_COOKIE_NAME}=${token}; path=/`;
    return HttpResponse.json({ detail: "CSRF cookie set." });
  }),

  http.post(`${BASE}/api/v1/auth/login/`, async ({ request }) => {
    mockState.loginCallCount += 1;

    if (mockState.loginNetworkError) {
      return HttpResponse.error();
    }

    const csrfRejection = requireCsrf(request);
    if (csrfRejection) return csrfRejection;

    if (mockState.loginRateLimited) {
      return HttpResponse.json(
        {
          error: {
            code: "rate_limited",
            message: "Request was throttled.",
            details: { retry_after: 30 },
          },
        },
        { status: 429 },
      );
    }

    const body = (await request.json()) as { email?: string; password?: string };
    if (body.email !== FIXTURE_USER.email || body.password !== FIXTURE_USER.password) {
      return HttpResponse.json(
        { error: { code: "authentication_failed", message: "Invalid email or password." } },
        { status: 401 },
      );
    }

    mockState.refreshCookieValid = true;
    const access = issueAccessToken();
    return HttpResponse.json({
      access,
      user: {
        id: FIXTURE_USER.id,
        email: FIXTURE_USER.email,
        display_name: FIXTURE_USER.display_name,
        workspaces: FIXTURE_USER.workspaces,
      },
    });
  }),

  http.post(`${BASE}/api/v1/auth/refresh/`, async ({ request }) => {
    mockState.refreshCallCount += 1;

    if (mockState.refreshNetworkError) {
      return HttpResponse.error();
    }

    const csrfRejection = requireCsrf(request);
    if (csrfRejection) return csrfRejection;

    if (!mockState.refreshCookieValid) {
      return HttpResponse.json(
        { error: { code: "authentication_failed", message: "Refresh token missing." } },
        { status: 401 },
      );
    }

    mockState.forceMeUnauthorized = false;
    const access = issueAccessToken();
    return HttpResponse.json({ access });
  }),

  http.post(`${BASE}/api/v1/auth/logout/`, async ({ request }) => {
    const csrfRejection = requireCsrf(request);
    if (csrfRejection) return csrfRejection;

    mockState.refreshCookieValid = false;
    mockState.currentAccessToken = null;
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${BASE}/api/v1/auth/me/`, ({ request }) => {
    mockState.meCallCount += 1;

    const authHeader = request.headers.get("authorization");
    const presentedToken = authHeader?.replace(/^Bearer\s+/i, "") ?? null;

    if (
      mockState.forceMeUnauthorized ||
      mockState.meAlwaysUnauthorized ||
      !presentedToken ||
      presentedToken !== mockState.currentAccessToken
    ) {
      return HttpResponse.json(
        {
          error: {
            code: "authentication_failed",
            message: "Authentication credentials were not provided.",
          },
        },
        { status: 401 },
      );
    }

    return HttpResponse.json({
      id: FIXTURE_USER.id,
      email: FIXTURE_USER.email,
      display_name: FIXTURE_USER.display_name,
      workspaces: FIXTURE_USER.workspaces,
    });
  }),
];
