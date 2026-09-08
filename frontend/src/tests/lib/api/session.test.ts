import { describe, expect, it } from "vitest";

import { login } from "@/features/auth/api";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { ensureFreshAccessToken, withAccessTokenRetry } from "@/lib/api/session";
import { getAccessToken } from "@/lib/api/token-store";
import { FIXTURE_USER, mockState } from "@/tests/msw/handlers";

async function loginFixtureUser() {
  await login({ email: FIXTURE_USER.email, password: FIXTURE_USER.password });
}

describe("withAccessTokenRetry", () => {
  it("returns data directly on a request that doesn't 401", async () => {
    await loginFixtureUser();
    const user = await withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/"));
    expect(user.email).toBe(FIXTURE_USER.email);
    expect(mockState.refreshCallCount).toBe(0);
  });

  it("refreshes once and retries once on a 401", async () => {
    await loginFixtureUser();
    // Simulate the in-memory access token having expired server-side.
    mockState.forceMeUnauthorized = true;

    const user = await withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/"));

    expect(user.email).toBe(FIXTURE_USER.email);
    expect(mockState.refreshCallCount).toBe(1);
    expect(mockState.meCallCount).toBe(2); // first 401, then the retry
  });

  it("dedupes N parallel 401s into exactly one refresh call", async () => {
    await loginFixtureUser();
    mockState.forceMeUnauthorized = true;

    const calls = Array.from({ length: 10 }, () =>
      withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")),
    );
    const results = await Promise.all(calls);

    expect(results).toHaveLength(10);
    results.forEach((user) => expect(user.email).toBe(FIXTURE_USER.email));
    expect(mockState.refreshCallCount).toBe(1);
  });

  it("throws a normalized ApiError and does not retry when refresh itself fails (invalid session)", async () => {
    // No prior login: no valid refresh cookie server-side.
    await expect(
      withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")),
    ).rejects.toMatchObject({ code: "authentication_failed", status: 401 });

    expect(mockState.refreshCallCount).toBe(1);
    expect(getAccessToken()).toBeNull();
  });

  it("clears the access token when refresh fails", async () => {
    await loginFixtureUser();
    expect(getAccessToken()).not.toBeNull();

    mockState.refreshCookieValid = false; // simulate an expired/revoked refresh session
    mockState.forceMeUnauthorized = true;

    await expect(withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/"))).rejects.toThrow();
    expect(getAccessToken()).toBeNull();
  });

  it("does not retry a second time if the retried request also 401s", async () => {
    // Refresh succeeds, but /me/ keeps failing even with the new token —
    // e.g. the user was deactivated mid-session.
    await loginFixtureUser();
    mockState.meAlwaysUnauthorized = true;

    await expect(
      withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")),
    ).rejects.toMatchObject({ code: "authentication_failed" });

    // Exactly one refresh, exactly two /me/ attempts (original + one retry) — no loop.
    expect(mockState.refreshCallCount).toBe(1);
    expect(mockState.meCallCount).toBe(2);
  });
});

describe("ensureFreshAccessToken", () => {
  it("reports a network_error result when refresh can't reach the network", async () => {
    await loginFixtureUser();
    mockState.refreshNetworkError = true;

    const result = await ensureFreshAccessToken();

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("network_error");
    }
  });

  it("reports an authentication_failed result when there is no valid refresh session", async () => {
    const result = await ensureFreshAccessToken();

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("authentication_failed");
      expect(result.error.status).toBe(401);
    }
  });

  it("propagates a network-error ApiError from the original request when refresh also can't reach the network", async () => {
    mockState.refreshNetworkError = true;

    await expect(
      withAccessTokenRetry(() => apiClient.GET("/api/v1/auth/me/")),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
