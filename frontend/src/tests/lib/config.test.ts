import { afterEach, describe, expect, it, vi } from "vitest";

describe("config", () => {
  const ORIGINAL_ENV = process.env.NEXT_PUBLIC_API_BASE_URL;

  afterEach(() => {
    process.env.NEXT_PUBLIC_API_BASE_URL = ORIGINAL_ENV;
    vi.resetModules();
  });

  it("exposes a normalized apiBaseUrl when the env var is a valid URL", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000/api/v1/";
    const { config } = await import("@/lib/config");
    expect(config.apiBaseUrl).toBe("http://localhost:8000/api/v1");
  });

  it("throws a clear error when the env var is missing", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "";
    await expect(import("@/lib/config")).rejects.toThrow(/Missing required environment variable/);
  });

  it("throws a clear error when the env var is not a valid absolute URL", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "not-a-url";
    await expect(import("@/lib/config")).rejects.toThrow(/must be a valid absolute URL/);
  });

  it("rejects non-http(s) protocols", async () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "ftp://example.com";
    await expect(import("@/lib/config")).rejects.toThrow(/must use http\(s\)/);
  });
});
