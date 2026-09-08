import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { createQueryClient } from "@/lib/query/query-client";

function getRetry() {
  const client = createQueryClient();
  const retry = client.getDefaultOptions().queries?.retry;
  if (typeof retry !== "function") {
    throw new Error("Expected the query client's default retry option to be a function.");
  }
  return retry as (failureCount: number, error: unknown) => boolean;
}

describe("createQueryClient retry policy", () => {
  it("retries network_error and timeout up to the bound", () => {
    const retry = getRetry();
    const networkError = new ApiError("offline", { code: "network_error", status: null });
    const timeoutError = new ApiError("timed out", { code: "timeout", status: null });

    expect(retry(0, networkError)).toBe(true);
    expect(retry(1, networkError)).toBe(true);
    expect(retry(2, networkError)).toBe(false); // bound reached
    expect(retry(0, timeoutError)).toBe(true);
  });

  it("retries internal_server_error (transient 5xx) up to the bound", () => {
    const retry = getRetry();
    const serverError = new ApiError("boom", { code: "internal_server_error", status: 500 });
    expect(retry(0, serverError)).toBe(true);
    expect(retry(2, serverError)).toBe(false);
  });

  it("never retries a definitive 4xx outcome", () => {
    const retry = getRetry();
    const codes = [
      "validation_error",
      "permission_denied",
      "not_found",
      "conflict",
      "rate_limited",
      "invalid_request",
    ] as const;
    for (const code of codes) {
      const error = new ApiError("nope", { code, status: 400 });
      expect(retry(0, error)).toBe(false);
    }
  });

  it("never retries a definitive authentication_failed — that's the session layer's job, not a query retry", () => {
    const retry = getRetry();
    const error = new ApiError("no session", { code: "authentication_failed", status: 401 });
    expect(retry(0, error)).toBe(false);
  });

  it("never retries an unexpected non-ApiError failure", () => {
    const retry = getRetry();
    expect(retry(0, new Error("unexpected"))).toBe(false);
  });

  it("mutations never retry", () => {
    const client = createQueryClient();
    expect(client.getDefaultOptions().mutations?.retry).toBe(false);
  });
});
