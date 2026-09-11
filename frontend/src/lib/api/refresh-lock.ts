/**
 * Cross-tab/cross-document coordination for refresh-token rotation (Phase
 * 22 Chunk 3A, PHASE22-3-04).
 *
 * The backend rotates the HttpOnly refresh cookie on every successful
 * `POST /api/v1/auth/refresh/` and blacklists the token that was just used
 * (`config/settings.py SIMPLE_JWT["ROTATE_REFRESH_TOKENS"]`/
 * `["BLACKLIST_AFTER_ROTATION"]`, both `True` — a deliberate, non-
 * negotiable security property this module never weakens). `session.ts`'s
 * `refreshInFlight` singleton already dedupes concurrent refresh calls
 * *within one document* — but it is a plain module-level variable, so it
 * cannot coordinate across a hard navigation (a new document is a new JS
 * realm) or across multiple tabs/windows of the same origin. Two such
 * independent documents can each read the *same* not-yet-rotated cookie
 * value and both attempt to refresh with it: only one succeeds (and
 * rotates the cookie), and the other gets a real, correct 401 — the
 * *token* was genuinely reused, from the backend's point of view — because
 * nothing serialized *when* each document sent its request.
 *
 * The Web Locks API (https://developer.mozilla.org/docs/Web/API/Web_Locks_API)
 * is exactly the primitive this needs: `navigator.locks.request` serializes
 * callers across every document sharing an origin (same browser profile),
 * with no data of any kind — sensitive or otherwise — passed through it;
 * the lock name below is the only thing "shared," and it carries no
 * session state. Under contention, a caller queues until the lock is free,
 * then runs its own callback against whatever the *current* cookie state
 * is at that moment — never a cached/shared result from whichever caller
 * held the lock before it. Each document therefore still performs its own
 * real `POST /api/v1/auth/refresh/` call and gets its own real access
 * token (in-memory only, per `token-store.ts` — access tokens are never
 * shared between documents, by design); serialization only ever changes
 * *when* that call is sent, guaranteeing it is never sent using a cookie
 * value another document's request is concurrently rotating away.
 *
 * Locks are held only for the duration of the wrapped callback and are
 * released automatically by the browser if the holding document is
 * destroyed (a crash, a hard navigation mid-request) — there is no
 * separate timeout/cleanup path to maintain here, and no way for a lock to
 * be held forever.
 *
 * Feature-detected, not required: an environment without `navigator.locks`
 * (an older browser, or this project's Vitest/jsdom unit-test environment,
 * which does not implement the Web Locks API at all) falls back to running
 * the callback directly — same-document dedup via `refreshInFlight` still
 * holds there; only the cross-document race this module specifically
 * closes is unavailable, exactly the same class of gap that existed before
 * this change, never worse.
 */

const REFRESH_LOCK_NAME = "supportpilot-auth-refresh";

function locksApi(): LockManager | null {
  if (typeof navigator === "undefined") {
    return null;
  }
  const candidate = (navigator as Navigator & { locks?: LockManager }).locks;
  return typeof candidate?.request === "function" ? candidate : null;
}

/**
 * Runs `fn` exclusively with respect to every other same-origin document
 * (tab, window, or a since-replaced previous document from a hard
 * navigation) also calling this function with the same lock name — never
 * with respect to anything else. Never throws for the *absence* of Web
 * Locks support itself; `fn`'s own errors still propagate normally.
 */
export function withCrossTabRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  const locks = locksApi();
  if (!locks) {
    return fn();
  }
  // `lib.dom.d.ts`'s `LockGrantedCallback<T>` types the callback's return
  // as `T` itself, not `T | PromiseLike<T>` — it doesn't reflect that the
  // real Web Locks API awaits a promise-returning callback before
  // resolving (https://w3c.github.io/web-locks/#dom-lockmanager-request,
  // step "Let callbackResult be OrdinaryCallFunction(...)" then "Let
  // callbackPromise be PromiseResolve(callbackResult)"). Explicit `<T>`
  // pins the real inner type so TS doesn't otherwise infer it as
  // `Promise<T>` from the callback's actual (unflattened-by-the-type)
  // return type, which would double-wrap the result.
  return locks.request<T>(
    REFRESH_LOCK_NAME,
    { mode: "exclusive" },
    fn as unknown as LockGrantedCallback<T>,
  );
}
