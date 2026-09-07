import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { login, logout } from "@/features/auth/api";
import { FIXTURE_USER, mockState } from "@/tests/msw/handlers";

describe("no token leak", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("never writes the access token to localStorage or sessionStorage after login", async () => {
    await login({ email: FIXTURE_USER.email, password: FIXTURE_USER.password });

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("never exposes the refresh token to JavaScript (no readable cookie carries it)", async () => {
    await login({ email: FIXTURE_USER.email, password: FIXTURE_USER.password });

    // The only cookie a real browser would let this frontend read at all is
    // the CSRF double-submit cookie — the refresh token is HttpOnly by
    // design (backend/accounts/services.py set_refresh_cookie) and never
    // appears in `document.cookie` in a real browser either. This asserts
    // the same holds for whatever mock/test infrastructure stands in for
    // cookies here.
    expect(document.cookie).not.toMatch(/refresh/i);
  });

  it("the logout-pending marker never carries a token, only a boolean flag", async () => {
    await login({ email: FIXTURE_USER.email, password: FIXTURE_USER.password });
    mockState.logoutNetworkError = true;

    await logout();

    // Something was written (the marker) — but it must never look like a
    // JWT (three base64url segments joined by dots) or contain the word
    // "token"/the access token value itself.
    expect(localStorage.length).toBe(1);
    const allValues = Object.values(localStorage).join(" ");
    expect(allValues).not.toMatch(/^ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
    expect(allValues.length).toBeLessThan(10); // just the "1" flag, not a serialized object/credential
  });
});
