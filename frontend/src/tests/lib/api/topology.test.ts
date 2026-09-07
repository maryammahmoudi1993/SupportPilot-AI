import { afterEach, describe, expect, it, vi } from "vitest";

function stubBrowserHostname(hostname: string) {
  const original = window.location;
  Object.defineProperty(window, "location", {
    value: { ...original, hostname },
    writable: true,
    configurable: true,
  });
  return () => {
    Object.defineProperty(window, "location", {
      value: original,
      writable: true,
      configurable: true,
    });
  };
}

/** Import a fresh topology.ts module with NEXT_PUBLIC_API_BASE_URL set to `apiBaseUrl`. */
async function loadTopologyWith(apiBaseUrl: string) {
  const original = process.env.NEXT_PUBLIC_API_BASE_URL;
  process.env.NEXT_PUBLIC_API_BASE_URL = apiBaseUrl;
  vi.resetModules();
  const mod = await import("@/lib/api/topology");
  process.env.NEXT_PUBLIC_API_BASE_URL = original;
  return mod;
}

describe("assertCsrfHostnameCompatible", () => {
  let restoreHostname: (() => void) | null = null;

  afterEach(() => {
    restoreHostname?.();
    restoreHostname = null;
    vi.resetModules();
  });

  it("allows a matching hostname (local dev: localhost === localhost, ports differ)", async () => {
    const { assertCsrfHostnameCompatible } = await loadTopologyWith("http://localhost:8000");
    restoreHostname = stubBrowserHostname("localhost");
    expect(() => assertCsrfHostnameCompatible()).not.toThrow();
  });

  it("allows a matching hostname (a same-host production deployment)", async () => {
    const { assertCsrfHostnameCompatible } = await loadTopologyWith(
      "https://supportpilot.example.com",
    );
    restoreHostname = stubBrowserHostname("supportpilot.example.com");
    expect(() => assertCsrfHostnameCompatible()).not.toThrow();
  });

  it("rejects a sibling-subdomain topology (api.example.com vs app.example.com)", async () => {
    const { assertCsrfHostnameCompatible, CsrfTopologyError } =
      await loadTopologyWith("https://api.example.com");
    restoreHostname = stubBrowserHostname("app.example.com");
    expect(() => assertCsrfHostnameCompatible()).toThrow(CsrfTopologyError);
  });

  it("rejects a wholly different API hostname", async () => {
    const { assertCsrfHostnameCompatible } = await loadTopologyWith(
      "https://some-other-app.internal",
    );
    restoreHostname = stubBrowserHostname("app.example.com");
    expect(() => assertCsrfHostnameCompatible()).toThrow(/does not match the browser/);
  });

  it("does not throw outside the browser (no window.location to compare against)", async () => {
    const { assertCsrfHostnameCompatible } = await loadTopologyWith("https://api.example.com");
    const originalWindow = globalThis.window;
    // @ts-expect-error -- simulating an SSR/build environment without `window`.
    delete globalThis.window;
    try {
      expect(() => assertCsrfHostnameCompatible()).not.toThrow();
    } finally {
      globalThis.window = originalWindow;
    }
  });
});
