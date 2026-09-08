/**
 * A single boolean marker recording "the user asked to sign out, but we
 * couldn't confirm the backend revoked the refresh token" — set when
 * `POST /api/v1/auth/logout/` fails (network/CSRF/server error) and
 * cleared once a later attempt succeeds.
 *
 * This is NOT a credential and never becomes one: it carries no token, no
 * user identity, nothing an attacker could use — just a boolean. It exists
 * so a page reload can't silently re-authenticate the user via a refresh
 * cookie that logout intended to kill (see README.md, "Logout"), and so a
 * warning can be shown consistently across tabs (localStorage, not
 * sessionStorage — the marker's whole purpose is to persist logout intent
 * beyond the tab that set it).
 *
 * No `storage` event listener is added: each tab checks this at its own
 * bootstrap time, which is enough to close the "reload silently
 * re-authenticates" gap without the complexity of live cross-tab
 * synchronization.
 */
const STORAGE_KEY = "sp_logout_pending";

function safeLocalStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    // Storage can throw in some environments (e.g. certain private-browsing
    // modes) — treat as unavailable rather than crashing the logout flow.
    return null;
  }
}

export function markLogoutPending(): void {
  safeLocalStorage()?.setItem(STORAGE_KEY, "1");
}

export function clearLogoutPending(): void {
  safeLocalStorage()?.removeItem(STORAGE_KEY);
}

export function isLogoutPending(): boolean {
  return safeLocalStorage()?.getItem(STORAGE_KEY) === "1";
}
