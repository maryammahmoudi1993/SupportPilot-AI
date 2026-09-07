/**
 * Validates a post-login "next" target so it can only ever navigate within
 * this application -- never to an attacker-controlled external site.
 */

// Whitespace or C0 control characters -- some browsers strip/ignore these
// from a URL, which can smuggle a scheme past a naive "/"-prefix check
// (e.g. a tab before "/evil.com" or before "javascript:...").
const CONTROL_OR_WHITESPACE = /[\x00-\x1f\s]/;

/** Default destination when no "next" param is present or it fails validation. */
export const DEFAULT_REDIRECT_TARGET = "/";

export function isSafeRedirectTarget(target: string | null | undefined): target is string {
  if (!target) {
    return false;
  }
  // Must be root-relative ("/x"), never protocol-relative ("//evil.com") or
  // a backslash variant some browsers normalize to "//" ("/\evil.com").
  if (!target.startsWith("/") || target.startsWith("//") || target.startsWith("/\\")) {
    return false;
  }
  if (CONTROL_OR_WHITESPACE.test(target)) {
    return false;
  }
  // Resolve against a fixed, unreachable dummy origin: if the result's
  // origin differs, the target smuggled a scheme/host past the checks
  // above (e.g. via percent-encoding) and must be rejected.
  try {
    const resolved = new URL(target, "http://sp-internal.invalid");
    if (resolved.origin !== "http://sp-internal.invalid") {
      return false;
    }
  } catch {
    return false;
  }
  return true;
}

/** Returns `target` if safe, otherwise the default in-app destination. */
export function resolveRedirectTarget(target: string | null | undefined): string {
  return isSafeRedirectTarget(target) ? target : DEFAULT_REDIRECT_TARGET;
}
