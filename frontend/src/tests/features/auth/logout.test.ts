import { describe, expect, it } from "vitest";

import { login, logout } from "@/features/auth/api";
import { isLogoutPending } from "@/lib/api/logout-intent";
import { getAccessToken } from "@/lib/api/token-store";
import { FIXTURE_USER, mockState } from "@/tests/msw/handlers";

async function loginFixtureUser() {
  await login({ email: FIXTURE_USER.email, password: FIXTURE_USER.password });
}

describe("logout — failure matrix", () => {
  it("A. success: clears local state, calls the server, reports complete", async () => {
    await loginFixtureUser();

    const result = await logout();

    expect(result).toBe("complete");
    expect(getAccessToken()).toBeNull();
    expect(isLogoutPending()).toBe(false);
    expect(mockState.refreshCookieValid).toBe(false); // server actually revoked it
  });

  it("B. network failure: local access token is cleared before the network call even resolves", async () => {
    await loginFixtureUser();
    mockState.logoutNetworkError = true;

    const pending = logout();
    // Synchronously true the instant the promise starts executing — an
    // async function body runs up to its first `await` before yielding, and
    // setAccessToken(null) is the first statement in logout().
    expect(getAccessToken()).toBeNull();

    await pending;
  });

  it("C. network failure: reports server_unconfirmed and marks logout pending", async () => {
    await loginFixtureUser();
    mockState.logoutNetworkError = true;

    const result = await logout();

    expect(result).toBe("server_unconfirmed");
    expect(isLogoutPending()).toBe(true);
    // The server never saw the request, so its idea of the session is
    // untouched — the whole reason a pending marker is needed.
    expect(mockState.refreshCookieValid).toBe(true);
  });

  it("E. a later successful logout clears a previously-pending marker", async () => {
    await loginFixtureUser();
    mockState.logoutNetworkError = true;
    expect(await logout()).toBe("server_unconfirmed");
    expect(isLogoutPending()).toBe(true);

    mockState.logoutNetworkError = false;
    const result = await logout();

    expect(result).toBe("complete");
    expect(isLogoutPending()).toBe(false);
  });

  it("a fresh successful login clears a stale pending marker from an earlier failed logout", async () => {
    await loginFixtureUser();
    mockState.logoutNetworkError = true;
    await logout();
    expect(isLogoutPending()).toBe(true);

    mockState.logoutNetworkError = false;
    await loginFixtureUser();

    expect(isLogoutPending()).toBe(false);
  });

  it("F. never writes anything resembling a token to localStorage across the whole matrix", async () => {
    await loginFixtureUser();
    mockState.logoutNetworkError = true;
    await logout();
    mockState.logoutNetworkError = false;
    await logout();

    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      const value = key ? localStorage.getItem(key) : null;
      expect(value).not.toMatch(/^ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
    }
  });
});
