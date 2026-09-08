import { expect, test } from "@playwright/test";

import { e2eData, formAlert, login } from "./fixtures";

const TOKEN_LIKE = /^ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;

async function readBrowserStorage(page: import("@playwright/test").Page) {
  return page.evaluate(() => ({
    localStorage: { ...localStorage },
    sessionStorage: { ...sessionStorage },
  }));
}

function assertNoAuthSecrets(storage: { localStorage: Record<string, string> }) {
  for (const [key, value] of Object.entries(storage.localStorage)) {
    expect(value, `localStorage["${key}"] must not look like a JWT`).not.toMatch(TOKEN_LIKE);
  }
}

test.describe("Login", () => {
  test("logs in, reaches /app with no auth secret in browser storage or the URL", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    expect(page.url()).not.toMatch(TOKEN_LIKE);
    expect(page.url()).not.toContain("access=");
    expect(page.url()).not.toContain("token=");

    const storage = await readBrowserStorage(page);
    assertNoAuthSecrets(storage);

    // Real backend proof: the refresh cookie the browser actually holds.
    const cookies = await page.context().cookies();
    const refreshCookie = cookies.find((c) => c.name === "sp_refresh_token");
    expect(refreshCookie, "refresh cookie must be set by the backend").toBeTruthy();
    expect(refreshCookie?.httpOnly).toBe(true);
    const csrfCookie = cookies.find((c) => c.name === "sp_csrftoken");
    expect(csrfCookie?.httpOnly).toBe(false);
  });

  test("shows an error and stays on /login for invalid credentials", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("not-a-real-user@example.com");
    await page.getByLabel("Password").fill("wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(formAlert(page)).toContainText(/incorrect email or password/i);
    expect(page.url()).toContain("/login");
  });
});

test.describe("Reload restoration", () => {
  test("a reload restores the authenticated session and workspace via the refresh cookie", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.reload();

    // The in-memory access token is gone (a real reload, not a client-side
    // navigation) — bootstrap must re-establish the session via the
    // HttpOnly refresh cookie alone.
    await page.waitForURL("**/app");
    await expect(page.getByText(/Signed in as/i)).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  });
});

test.describe("Logout", () => {
  test("logs out via the user menu: shell disappears, cookie is revoked, Back doesn't restore it", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();

    const cookiesAfterLogout = await page.context().cookies();
    const refreshCookie = cookiesAfterLogout.find((c) => c.name === "sp_refresh_token");
    expect(refreshCookie, "the server must have cleared the refresh cookie").toBeFalsy();

    // Browser Back must not resurrect a usable authenticated shell. In this
    // app both the post-login and post-logout redirects use
    // `router.replace()` (never `router.push()`), so `/app` never becomes
    // its own distinct, back-traversable history entry in the first place —
    // a stronger guarantee than merely showing stale content: there is
    // nothing to go "back" *to*. Depending on what history existed before
    // this session, `goBack()` may land on a blank/unrelated prior entry
    // rather than the login form — the one thing that must hold regardless
    // is that the privileged shell never reappears.
    await page.goBack();
    await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Account menu/i })).toHaveCount(0);

    // `goBack()`'s destination isn't asserted further (it may be a blank
    // pre-session history entry, not necessarily `/login` — see above); a
    // fresh, independent navigation is what actually proves the session
    // stays gone, rather than reloading whatever unpredictable page Back
    // landed on.
    await page.goto("/app");
    await page.waitForURL("**/login");
  });

  test("a failed (network-level) logout still clears the shell immediately and reports it honestly", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // Fail only the logout POST at the network level — everything else
    // (login, /me/, workspaces) still went to the real backend.
    await page.route("**/api/v1/auth/logout/", (route) => route.abort("failed"));

    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();

    await page.waitForURL("**/login");
    await expect(page.locator("main")).toContainText(/couldn't confirm/i);

    const storage = await readBrowserStorage(page);
    assertNoAuthSecrets(storage);
    expect(storage.localStorage["sp_logout_pending"]).toBe("1");

    // Restore the network, and prove the pending revocation resolves on
    // the next bootstrap rather than staying stuck. `reload()` only waits
    // for the page's "load" event, not for AuthProvider's async retry (the
    // page is already at /login before reloading, so `waitForURL` resolves
    // immediately too) — poll the actual signal (the marker itself, then
    // the UI) instead of reading a single snapshot right after reload.
    await page.unroute("**/api/v1/auth/logout/");
    await page.reload();
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("sp_logout_pending")), {
        timeout: 10_000,
      })
      .toBeNull();
    await expect(page.locator("main")).not.toContainText(/couldn't confirm/i);
  });

  test("an explicit login after a pending logout supersedes it and survives a reload", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.route("**/api/v1/auth/logout/", (route) => route.abort("failed"));
    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await page.waitForURL("**/login");
    await page.unroute("**/api/v1/auth/logout/");

    let storage = await readBrowserStorage(page);
    expect(storage.localStorage["sp_logout_pending"]).toBe("1");

    await page.getByLabel("Email").fill(data.primaryEmail);
    await page.getByLabel("Password").fill(data.primaryPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL("**/app");

    storage = await readBrowserStorage(page);
    expect(storage.localStorage["sp_logout_pending"]).toBeUndefined();

    await page.reload();
    await page.waitForURL("**/app");
  });
});

test.describe("Session uncertainty (real browser, network interception)", () => {
  test("an initial network failure shows SessionVerificationError, never a /login redirect or the shell", async ({
    page,
  }) => {
    // Everything the initial bootstrap can call fails at the network level.
    await page.route("**/api/v1/auth/refresh/", (route) => route.abort("failed"));
    await page.route("**/api/v1/auth/csrf/", (route) => route.abort("failed"));

    await page.goto("/app");

    await expect(page.getByText("We couldn't verify your session")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    expect(page.url()).not.toContain("/login");
    await page.waitForTimeout(1000);
    expect(page.url()).not.toContain("/login");
  });

  test("uncertain -> Retry -> valid session restores the app shell and workspace", async ({
    page,
  }) => {
    const data = e2eData();
    // Log in normally first so a real refresh cookie exists.
    await login(page, data.primaryEmail, data.primaryPassword);

    // Simulate a reload landing on a network outage.
    await page.route("**/api/v1/auth/refresh/", (route) => route.abort("failed"));
    await page.reload();
    await expect(page.getByText("We couldn't verify your session")).toBeVisible();

    await page.unroute("**/api/v1/auth/refresh/");
    await page.getByRole("button", { name: "Retry" }).click();

    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
    // Both the header switcher and the /app overview card show the
    // workspace name — the switcher button is the specific, unambiguous proof.
    await expect(page.getByRole("button", { name: data.defaultWorkspaceName })).toBeVisible();
  });

  test("uncertain -> Retry -> confirmed invalid session redirects to /login, not stuck uncertain", async ({
    page,
  }) => {
    await page.route("**/api/v1/auth/refresh/", (route) => route.abort("failed"));
    await page.goto("/app");
    await expect(page.getByText("We couldn't verify your session")).toBeVisible();

    // The retry reaches the real backend, which has no session for this
    // browser context at all (no cookie jar) — a definitive 401.
    await page.unroute("**/api/v1/auth/refresh/");
    await page.getByRole("button", { name: "Retry" }).click();

    await page.waitForURL("**/login");
  });

  test("/me/ failing after a successful refresh eventually resolves to uncertain, not an infinite spinner", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // Refresh succeeds (real cookie); /me/ itself is aborted every time.
    await page.route("**/api/v1/auth/me/", (route) => route.abort("failed"));
    await page.reload();

    await expect(page.getByText("We couldn't verify your session")).toBeVisible({
      timeout: 20_000,
    });
  });
});
