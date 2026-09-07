/**
 * Persists the user's last-selected workspace ID across reloads. This is a
 * UX preference, not a credential or an authorization decision: it is a
 * workspace UUID (see `workspaces/models.py` — the security-safe identifier,
 * already treated as non-secret throughout the backend), and every request
 * that uses it remains subject to full server-side membership/permission
 * checks regardless of what this value says (see workspace-provider.tsx).
 *
 * `localStorage` (not `sessionStorage`) is deliberate: the preference should
 * survive a reload/new tab, the same way a browser remembers other UI
 * preferences. It is scoped per browser profile, not per account — a
 * different account signing in on the same browser simply finds its stored
 * ID absent from its own membership list and falls back safely (see
 * "discards a stale/inaccessible persisted ID" in workspace-provider.tsx).
 */
const STORAGE_KEY = "sp_active_workspace_id";

function safeLocalStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    // Some browser configurations (private mode, blocked site data) throw on
    // access rather than returning undefined.
    return null;
  }
}

export function getStoredActiveWorkspaceId(): string | null {
  return safeLocalStorage()?.getItem(STORAGE_KEY) ?? null;
}

export function setStoredActiveWorkspaceId(id: string): void {
  safeLocalStorage()?.setItem(STORAGE_KEY, id);
}

export function clearStoredActiveWorkspaceId(): void {
  safeLocalStorage()?.removeItem(STORAGE_KEY);
}
