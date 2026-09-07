/**
 * Guards the one topology invariant this frontend's CSRF design actually
 * depends on: the browser must be able to read, via JavaScript, a cookie
 * the backend set.
 *
 * That is a *hostname* question, not a *site* or *SameSite* one — three
 * different things this codebase must not conflate (see README.md,
 * "Cookie semantics"):
 *
 * - **Origin** = scheme + host + port. `http://localhost:3000` and
 *   `http://localhost:8000` are different origins.
 * - **Site** (for `SameSite`) = registrable domain (eTLD+1), ignoring
 *   scheme/port. `app.example.com` and `api.example.com` are the same
 *   *site* — `SameSite=Lax` cookies are sent on requests between them.
 * - **Cookie readability** (what this guard checks) is governed by the
 *   cookie's `Domain` attribute, matched against the exact *hostname* of
 *   the page running the JavaScript — ports are irrelevant, but
 *   subdomains are NOT automatically included unless the cookie explicitly
 *   sets a shared parent `Domain` (e.g. `Domain=.example.com`).
 *
 * The backend sets `sp_csrftoken` with no explicit `Domain`
 * (`backend/config/settings.py` has no `CSRF_COOKIE_DOMAIN`), making it a
 * **host-only** cookie: readable only by JavaScript running on the exact
 * host that received it. Two different hostnames — even sibling
 * subdomains of the same registrable domain, which pass the *site* check
 * fine — cannot share it. `localhost:3000` and `localhost:8000` work
 * *only* because they share the literal hostname `localhost`; a
 * `app.example.com` frontend calling an `api.example.com` backend would
 * not, even though that pair is same-site.
 */
import { config } from "@/lib/config";

export class CsrfTopologyError extends Error {
  constructor(apiHostname: string, browserHostname: string) {
    super(
      `NEXT_PUBLIC_API_BASE_URL's hostname ("${apiHostname}") does not match the ` +
        `browser's hostname ("${browserHostname}"). This frontend's CSRF flow needs ` +
        `to read a cookie the backend sets with no explicit cookie Domain, which only ` +
        `works when both are served from the exact same hostname — a sibling ` +
        `subdomain is not enough. Route the API under the same host instead (e.g. a ` +
        `reverse proxy serving both the app and /api/v1/ from one hostname). See ` +
        `frontend/README.md, "Production topology".`,
    );
    this.name = "CsrfTopologyError";
  }
}

/**
 * Throws `CsrfTopologyError` if the configured API hostname can't match the
 * browser's own hostname closely enough for this frontend's CSRF cookie to
 * be readable. A no-op outside the browser (SSR/build — there's no
 * `window.location` to compare against yet, and nothing CSRF-dependent
 * runs at that point either).
 */
export function assertCsrfHostnameCompatible(): void {
  if (typeof window === "undefined") {
    return;
  }
  const apiHostname = new URL(config.apiBaseUrl).hostname;
  const browserHostname = window.location.hostname;
  if (apiHostname !== browserHostname) {
    throw new CsrfTopologyError(apiHostname, browserHostname);
  }
}
