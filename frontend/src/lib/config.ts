/**
 * Frontend runtime configuration.
 *
 * Every value read here must already be validated — nothing downstream
 * should read `process.env` directly. Fails fast and loudly on invalid or
 * missing critical configuration rather than silently falling back to
 * `localhost` in a build that never meant to talk to it.
 */

function requireUrl(name: string, value: string | undefined): string {
  if (!value || value.trim().length === 0) {
    throw new Error(
      `Missing required environment variable ${name}. Copy .env.example to .env.local and set it.`,
    );
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`Environment variable ${name} must be a valid absolute URL, got: ${value}`);
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`Environment variable ${name} must use http(s), got: ${value}`);
  }

  // Strip a trailing slash so callers can join paths predictably.
  return value.replace(/\/+$/, "");
}

export const config = {
  /** Base URL of the backend API, including the version prefix (e.g. `/api/v1`). */
  apiBaseUrl: requireUrl("NEXT_PUBLIC_API_BASE_URL", process.env.NEXT_PUBLIC_API_BASE_URL),
} as const;
