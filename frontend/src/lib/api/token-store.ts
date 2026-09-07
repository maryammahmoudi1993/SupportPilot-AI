/**
 * In-memory access-token holder and session-expiry notification.
 *
 * Deliberately not a React module — client.ts's request middleware and
 * session.ts's refresh coordination both need synchronous read/write access
 * to the current access token outside of any component tree, and neither
 * should import the other (see README.md, "Security notes" /
 * "Auth architecture" for the full dependency graph this keeps acyclic).
 *
 * The access token lives ONLY here, in memory. It is never written to
 * localStorage/sessionStorage/a cookie the frontend controls, and it is lost
 * on a full page reload by design — reload re-establishes it through
 * ensureFreshAccessToken() (session.ts), which relies on the backend's
 * HttpOnly refresh cookie, not on frontend-held state surviving the reload.
 */

let accessToken: string | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

type SessionExpiredHandler = () => void;

let sessionExpiredHandler: SessionExpiredHandler | null = null;

/**
 * Registered by AuthProvider (features/auth) so any code that discovers the
 * session is no longer valid — a failed refresh triggered from anywhere,
 * not just a component the user happens to be looking at — can drive the
 * app's auth state to "unauthenticated" through one owner, without
 * lib/api/session.ts importing React or the auth feature.
 */
export function setSessionExpiredHandler(handler: SessionExpiredHandler | null): void {
  sessionExpiredHandler = handler;
}

export function notifySessionExpired(): void {
  sessionExpiredHandler?.();
}

/** Test-only: reset all module state between tests. */
export function __resetTokenStoreForTests(): void {
  accessToken = null;
  sessionExpiredHandler = null;
}
