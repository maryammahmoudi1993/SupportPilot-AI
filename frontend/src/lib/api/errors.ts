/**
 * Typed representation of the backend's error envelope.
 *
 * Every handled backend error response has the shape
 * `{ "error": { "code": string, "message": string, "details"?: unknown } }`
 * (see backend/common/exceptions.py:custom_exception_handler). This module
 * normalizes any API failure — a well-formed envelope, a malformed body, a
 * network failure, or a timeout — into one typed `ApiError` so UI code
 * never has to branch on how a request failed.
 */

/** Stable, client-facing error codes the backend is known to emit. */
export type ApiErrorCode =
  | "validation_error"
  | "authentication_failed"
  | "permission_denied"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "internal_server_error"
  | "invalid_request"
  // Frontend-only codes for failures that never reached a backend handler.
  | "network_error"
  | "timeout"
  | "parse_error"
  | "unknown_error";

export interface ApiErrorDetails {
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number | null;
  readonly details: ApiErrorDetails | undefined;

  constructor(
    message: string,
    options: { code: ApiErrorCode; status: number | null; details?: ApiErrorDetails },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.details = options.details;
  }
}

/** Narrow an unknown JSON body into the backend's `{ error: {...} }` shape, if it matches. */
function asBackendEnvelope(
  body: unknown,
): { error: { code?: unknown; message?: unknown; details?: unknown } } | null {
  if (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof (body as Record<string, unknown>).error === "object" &&
    (body as Record<string, unknown>).error !== null
  ) {
    return body as { error: { code?: unknown; message?: unknown; details?: unknown } };
  }
  return null;
}

const KNOWN_CODES: ReadonlySet<string> = new Set([
  "validation_error",
  "authentication_failed",
  "permission_denied",
  "not_found",
  "conflict",
  "rate_limited",
  "internal_server_error",
  "invalid_request",
]);

/** Build an ApiError from a parsed (or unparseable) HTTP response body. */
export function normalizeHttpError(status: number, body: unknown): ApiError {
  const envelope = asBackendEnvelope(body);
  if (envelope) {
    const rawCode = envelope.error.code;
    const code: ApiErrorCode =
      typeof rawCode === "string" && KNOWN_CODES.has(rawCode)
        ? (rawCode as ApiErrorCode)
        : "unknown_error";
    const message =
      typeof envelope.error.message === "string" && envelope.error.message.length > 0
        ? envelope.error.message
        : "The request failed.";
    const details =
      typeof envelope.error.details === "object" && envelope.error.details !== null
        ? (envelope.error.details as ApiErrorDetails)
        : undefined;
    return new ApiError(message, { code, status, details });
  }

  // The response wasn't the expected envelope (unexpected proxy error page,
  // etc). Never surface raw body content to the user.
  return new ApiError("The server returned an unexpected response.", {
    code: "parse_error",
    status,
  });
}

/**
 * True for a failure that means "we couldn't find out" (network unreachable,
 * timed out) as opposed to one that means "we found out, and the session is
 * genuinely invalid" (e.g. `authentication_failed` for a missing/expired
 * refresh token). Callers that need to tell "please retry" from "please log
 * in" — AuthProvider's bootstrap, WorkspaceProvider's derived status — key
 * off this rather than "is there an ApiError at all", since an ordinary
 * "no session yet" bootstrap also produces an ApiError.
 */
export function isUncertainSessionError(error: ApiError): boolean {
  return error.code === "network_error" || error.code === "timeout";
}

/** Build an ApiError for a request that never got an HTTP response at all. */
export function normalizeTransportError(cause: unknown): ApiError {
  if (cause instanceof DOMException && cause.name === "AbortError") {
    return new ApiError("The request timed out. Please try again.", {
      code: "timeout",
      status: null,
    });
  }
  return new ApiError("Unable to reach the server. Check your connection and try again.", {
    code: "network_error",
    status: null,
  });
}
