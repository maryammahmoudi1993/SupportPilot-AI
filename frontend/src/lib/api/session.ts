/**
 * Coordinated access-token refresh and the 401 → refresh → retry-once flow
 * for protected requests.
 *
 * This is the piece that makes the "10 parallel requests get 401, only 1
 * refresh happens" invariant hold: `ensureFreshAccessToken()` is a mutex —
 * every caller while a refresh is already in flight awaits the same
 * promise instead of starting its own. `refreshInFlight` is a same-document
 * mutex only; `withCrossTabRefreshLock` (refresh-lock.ts) additionally
 * serializes across tabs/windows/hard-navigation-replaced documents — see
 * that module's doc comment for the full PHASE22-3-04 race this closes.
 */
import { apiClient } from "@/lib/api/client";
import { ensureCsrfCookie } from "@/lib/api/csrf";
import { ApiError, normalizeTransportError } from "@/lib/api/errors";
import { withCrossTabRefreshLock } from "@/lib/api/refresh-lock";
import { requestWithTimeout, unwrap } from "@/lib/api/request";
import { notifySessionExpired, setAccessToken } from "@/lib/api/token-store";

/**
 * The backend's schema for `POST /api/v1/auth/refresh/` documents only the
 * 200 status (`content?: never`) — it doesn't describe the actual
 * `{ access: string }` body the view returns (accounts/views.py
 * `TokenRefreshCookieView`), because the endpoint declares its response via
 * `OpenApiResponse(description=...)` rather than a response serializer. This
 * is a real generated-schema gap (see frontend/README.md, "API contract"),
 * not something to paper over with `any` — this interface documents exactly
 * what's missing and nothing more.
 */
interface RefreshResponseBody {
  access: string;
}

export type RefreshResult = { ok: true } | { ok: false; error: ApiError };

let refreshInFlight: Promise<RefreshResult> | null = null;

/**
 * Refresh the access token via the HttpOnly refresh cookie, coordinating
 * concurrent callers onto a single in-flight request. On success, updates
 * the in-memory access token and returns `{ok: true}`. On failure, clears
 * the access token, notifies the registered session-expired handler, and
 * returns `{ok: false, error}` — `error.code` distinguishes an actually
 * invalid/expired session (`authentication_failed`) from a refresh attempt
 * that couldn't reach the network at all (`network_error`/`timeout`), so a
 * caller can tell "you're logged out" from "try again" (see
 * `withAccessTokenRetry` below and AuthProvider's `error` field).
 *
 * Cross-tab/hard-navigation safety (PHASE22-3-04): the actual network call
 * below runs inside `withCrossTabRefreshLock`, which additionally
 * serializes it against every other same-origin document doing the same —
 * never against anything else, and never sharing any token material to do
 * so (see refresh-lock.ts). `refreshInFlight` still short-circuits a
 * same-document duplicate call without even reaching the lock.
 */
export function ensureFreshAccessToken(): Promise<RefreshResult> {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  refreshInFlight = withCrossTabRefreshLock(async (): Promise<RefreshResult> => {
    try {
      // `ensureCsrfCookie()` bounds its own priming request internally
      // (see csrf.ts) — this refresh call gets its own separate bounded
      // window via `requestWithTimeout` below, the same central mechanism
      // every other auth-critical request uses (see frontend/README.md,
      // "Auth request timeout policy"). Without this, a refresh request
      // that never gets a response (the backend hangs, a proxy silently
      // drops it, ...) would leave AuthProvider stuck in "loading"
      // indefinitely — there would be no failure to classify as
      // "uncertain" at all. The resulting `AbortError` on timeout is what
      // `normalizeTransportError` maps to a "timeout" ApiError, which
      // `isUncertainSessionError` treats the same as a plain network
      // failure — never as a confirmed invalid session.
      //
      // `keepalive: true` (PHASE22-3-04, reclassified — see refresh-lock.ts
      // and README.md): a hard navigation starting while this request is
      // still in flight normally aborts it client-side. If the request had
      // already reached the backend by then, the *server* can still fully
      // commit the rotation (new token issued, old one blacklisted) before
      // the connection drops — the browser then never applies the
      // response's `Set-Cookie`, silently leaving the cookie jar holding a
      // refresh token the backend has already invalidated. Every later
      // attempt (from this document or a fresh one) then fails, correctly
      // but unrecoverably, on a token that really was already consumed —
      // not a race between two competing rotations (the lock above already
      // prevents that), but a single rotation whose own response was lost.
      // `keepalive` (https://fetch.spec.whatwg.org/#request-keepalive-flag)
      // is the browser-native primitive for exactly this: it lets the
      // browser finish an in-flight fetch — including applying its
      // response's `Set-Cookie` — even after the initiating document is
      // gone, the same mechanism `navigator.sendBeacon` relies on, just
      // with the custom CSRF header this endpoint requires. The request
      // carries no body (well under every browser's keepalive payload
      // cap), and the existing `signal`-based timeout still applies
      // unchanged for a genuinely slow/hung backend — this only changes
      // what happens on navigation-triggered abandonment, never on an
      // explicit timeout.
      await ensureCsrfCookie();
      const body = await requestWithTimeout<RefreshResponseBody>(
        (signal) =>
          // Cast documented in the interface above: the generated response
          // type is `content?: never`, which doesn't reflect the real body.
          apiClient.POST("/api/v1/auth/refresh/", { signal, keepalive: true }) as unknown as Promise<{
            data?: RefreshResponseBody;
            error?: unknown;
            response: Response;
          }>,
      );
      setAccessToken(body.access);
      return { ok: true };
    } catch (err) {
      setAccessToken(null);
      const apiError = err instanceof ApiError ? err : normalizeTransportError(err);
      notifySessionExpired(apiError);
      return { ok: false, error: apiError };
    } finally {
      refreshInFlight = null;
    }
  });

  return refreshInFlight;
}

interface OpenApiFetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/**
 * Run a protected request, and on a 401 (expired/missing access token),
 * refresh once (coordinated via `ensureFreshAccessToken`) and retry the
 * request exactly once. `callFactory` is invoked again from scratch on
 * retry — never re-sent from a consumed `Request`/body — so this is safe
 * for POST/PATCH/DELETE as long as the *first* attempt never reached
 * business logic (a 401 means it didn't: JWTAuthentication rejects before
 * the view runs).
 *
 * If refresh itself fails, the *refresh's* error is thrown (not the
 * original request's 401) — that's what preserves the network-vs-invalid-
 * session distinction for the caller.
 *
 * NOT used by login/refresh/logout themselves — they call `apiClient`
 * directly and `unwrap()` without this wrapper, which is what keeps this
 * flow from ever recursing into itself.
 */
export async function withAccessTokenRetry<T>(
  callFactory: () => Promise<OpenApiFetchResult<T>>,
): Promise<T> {
  try {
    return await unwrap(callFactory());
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      const result = await ensureFreshAccessToken();
      if (result.ok) {
        return await unwrap(callFactory());
      }
      throw result.error;
    }
    throw err;
  }
}

/** Test-only: reset in-flight refresh state between tests. */
export function __resetSessionForTests(): void {
  refreshInFlight = null;
}
