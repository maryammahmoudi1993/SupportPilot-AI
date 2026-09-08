/**
 * Minimal, dependency-free cookie reader for the one browser-readable cookie
 * the frontend needs: the CSRF double-submit cookie (see lib/api/csrf.ts).
 * Never used for the refresh token — that cookie is HttpOnly and
 * intentionally invisible to JavaScript.
 */
export function getCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}
