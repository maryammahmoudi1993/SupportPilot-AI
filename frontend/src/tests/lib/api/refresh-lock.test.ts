import { afterEach, describe, expect, it, vi } from "vitest";

import { withCrossTabRefreshLock } from "@/lib/api/refresh-lock";

/**
 * jsdom (this project's Vitest environment) does not implement the Web
 * Locks API at all — `navigator.locks` is genuinely `undefined` here,
 * verified directly. That makes this the correct place to test both the
 * feature-detected fallback (real, exercised by every other test in this
 * suite that touches `ensureFreshAccessToken`) and the Web-Locks-present
 * path (only reachable by installing a fake `navigator.locks` for the
 * duration of one test — the real path is proven for real by the
 * multi-tab/hard-navigation Playwright coverage, e2e/auth-refresh-*.spec.ts).
 */
describe("withCrossTabRefreshLock", () => {
  afterEach(() => {
    delete (navigator as { locks?: unknown }).locks;
  });

  it("runs fn directly when navigator.locks is unavailable (this environment)", async () => {
    expect((navigator as { locks?: unknown }).locks).toBeUndefined();

    const fn = vi.fn().mockResolvedValue("direct-result");
    const result = await withCrossTabRefreshLock(fn);

    expect(result).toBe("direct-result");
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("propagates fn's rejection when Web Locks is unavailable", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("boom"));

    await expect(withCrossTabRefreshLock(fn)).rejects.toThrow("boom");
  });

  it("requests an exclusive lock by a stable name and runs fn only once granted", async () => {
    const request = vi.fn(
      async (
        _name: string,
        _options: { mode: string },
        callback: () => Promise<unknown>,
      ) => callback(),
    );
    Object.defineProperty(navigator, "locks", {
      configurable: true,
      value: { request },
    });

    const fn = vi.fn().mockResolvedValue("locked-result");
    const result = await withCrossTabRefreshLock(fn);

    expect(result).toBe("locked-result");
    expect(request).toHaveBeenCalledTimes(1);
    const [name, options] = request.mock.calls[0] as [string, { mode: string }, unknown];
    expect(name).toBe("supportpilot-auth-refresh");
    expect(options).toEqual({ mode: "exclusive" });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("never passes any token/session material into the lock request itself", async () => {
    const request = vi.fn(
      async (
        _name: string,
        _options: { mode: string },
        callback: () => Promise<unknown>,
      ) => callback(),
    );
    Object.defineProperty(navigator, "locks", {
      configurable: true,
      value: { request },
    });

    await withCrossTabRefreshLock(async () => "ok");

    // The only arguments the Web Locks API itself ever sees are a fixed,
    // static lock name (a coordination label, not a secret) and a plain
    // options object — no access token, refresh token, or any other
    // session-derived value is ever part of the coordination signal
    // (master prompt Part 6/16).
    const [name, options] = request.mock.calls[0] as [string, { mode: string }, unknown];
    expect(name).toBe("supportpilot-auth-refresh");
    expect(JSON.stringify(name)).not.toMatch(/token|secret|jwt|bearer/i);
    expect(JSON.stringify(options)).toBe(JSON.stringify({ mode: "exclusive" }));
  });
});
