/**
 * In-memory access-token holder and session-expiry notification.
 *
 * Deliberately not a React module — client.ts's request middleware and
 * session.ts's refresh coordination both need synchronous read/write access
 * to the current access token outside of any component tree, and neither
 * should import the other (see README.md, "Security notes" /
 * "Auth architecture" for the full dependency graph this keeps acyclic).
 * This module also stays free of any dependency on `errors.ts`'s
 * `ApiError` class beyond its type — it forwards whatever `session.ts`
 * classified without re-deriving that classification itself.
 *
 * The access token lives ONLY here, in memory. It is never written to
 * localStorage/sessionStorage/a cookie the frontend controls, and it is lost
 * on a full page reload by design — reload re-establishes it through
 * ensureFreshAccessToken() (session.ts), which relies on the backend's
 * HttpOnly refresh cookie, not on frontend-held state surviving the reload.
 */
import type { ApiError } from "@/lib/api/errors";

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

type SessionExpiredHandler = (error: ApiError) => void;

let sessionExpiredHandler: SessionExpiredHandler | null = null;

/**
 * Registered by AuthProvider (features/auth) so any code that discovers a
 * refresh failed — triggered from anywhere, not just a component the user
 * happens to be looking at — can drive the app's auth state through one
 * owner, without lib/api/session.ts importing React or the auth feature.
 * The handler receives the classified `ApiError` (see
 * `errors.ts`'s `isUncertainSessionError`) so it can tell a confirmed-invalid
 * session from one that merely couldn't be verified — collapsing that
 * distinction here, before it ever reaches AuthProvider, is exactly the bug
 * fixed in Phase 18 Chunk 3A (see README.md, "Session state model").
 */
export function setSessionExpiredHandler(handler: SessionExpiredHandler | null): void {
  sessionExpiredHandler = handler;
}

export function notifySessionExpired(error: ApiError): void {
  sessionExpiredHandler?.(error);
}

/** Test-only: reset all module state between tests. */
export function __resetTokenStoreForTests(): void {
  accessToken = null;
  sessionExpiredHandler = null;
}
