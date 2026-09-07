/**
 * Thin helpers layered on top of `apiClient` (see client.ts).
 *
 * `openapi-fetch` returns `{ data, error, response }` rather than throwing on
 * a non-2xx response. `unwrap` converts that into throw-on-failure form with
 * a normalized `ApiError`, for the common case where a component just wants
 * the data or a typed error to render. Code that needs to branch on
 * `{ data, error }` directly (e.g. to distinguish "not found" from other
 * failures without a try/catch) can call `apiClient` directly instead.
 */
import { DEFAULT_TIMEOUT_MS } from "@/lib/api/client";
import { ApiError, normalizeHttpError, normalizeTransportError } from "@/lib/api/errors";
import { withTimeout } from "@/lib/api/timeout";

interface OpenApiFetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

export async function unwrap<T>(resultPromise: Promise<OpenApiFetchResult<T>>): Promise<T> {
  let result: OpenApiFetchResult<T>;
  try {
    result = await resultPromise;
  } catch (cause) {
    throw normalizeTransportError(cause);
  }

  if (result.error !== undefined) {
    throw normalizeHttpError(result.response.status, result.error);
  }

  if (result.data === undefined) {
    // A successful response can legitimately have no body — 204 No Content
    // (e.g. POST /auth/logout/) always does, per HTTP semantics, not just
    // per this backend's convention. Only treat a *missing* body as an
    // error for statuses that are expected to carry one.
    if (result.response.status === 204 || result.response.status === 304) {
      return undefined as T;
    }
    throw new ApiError("The server returned an empty response.", {
      code: "parse_error",
      status: result.response.status,
    });
  }

  return result.data;
}

/**
 * Test-only: force every subsequent `withRequestTimeout`/`requestWithTimeout`
 * call to use this timeout instead of whatever the caller requested — the
 * one place a test shrinks a real request timeout, rather than each call
 * site inventing its own override (see Phase 18 Chunk 3B's "centralize, don't
 * copy timeout code"). `null` clears the override (the default).
 */
let timeoutOverrideMs: number | null = null;
export function __setTimeoutOverrideForTests(ms: number | null): void {
  timeoutOverrideMs = ms;
}

/**
 * Run `fn` with an AbortSignal that fires after `timeoutMs`, optionally
 * chained to a caller-provided signal (e.g. from a React Query cancellation
 * or a component unmount). Always cleans up its timer/listener afterwards.
 */
export async function withRequestTimeout<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
  callerSignal?: AbortSignal,
): Promise<T> {
  const { signal, dispose } = withTimeout(timeoutOverrideMs ?? timeoutMs, callerSignal);
  try {
    return await fn(signal);
  } finally {
    dispose();
  }
}

/**
 * The one request path every auth-critical call (login, refresh, logout,
 * `/me/`, CSRF priming) goes through: a bounded, abortable request, unwrapped
 * into throw-on-failure form. Centralizing `unwrap(withRequestTimeout(...))`
 * here — rather than each call site composing the two — is what keeps the
 * timeout wiring from being copy-pasted four times (see
 * frontend/README.md, "Auth request timeout policy").
 */
export function requestWithTimeout<T>(
  fn: (signal: AbortSignal) => Promise<OpenApiFetchResult<T>>,
  timeoutMs?: number,
): Promise<T> {
  return unwrap(withRequestTimeout(fn, timeoutMs));
}
