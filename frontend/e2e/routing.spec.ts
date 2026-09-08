import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

test.describe("Protected routing", () => {
  test("an unauthenticated visitor to /app is redirected to /login with no shell flash", async ({
    page,
  }) => {
    await page.goto("/app");
    await page.waitForURL("**/login");
    await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);
  });

  test("a safe internal ?next target is honored after login", async ({ page }) => {
    const data = e2eData();
    await page.goto("/login?next=%2Fapp");
    await page.getByLabel("Email").fill(data.primaryEmail);
    await page.getByLabel("Password").fill(data.primaryPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL("**/app");
  });

  test("rejects an unsafe absolute ?next target end-to-end, in a real browser, on a real login", async ({
    page,
  }) => {
    // This is the one real-browser instance of the redirect-safety proof —
    // isSafeRedirectTarget()/resolveRedirectTarget() are already exhaustively
    // unit-tested for every vector (protocol-relative, javascript:, control
    // characters, ...; see src/tests/features/auth/redirect.test.ts), so this
    // doesn't repeat all of them against the real backend — just proves the
    // wiring holds end-to-end for one representative case.
    const data = e2eData();
    await page.goto(`/login?next=${encodeURIComponent("https://evil.example")}`);
    await page.getByLabel("Email").fill(data.primaryEmail);
    await page.getByLabel("Password").fill(data.primaryPassword);
    await page.getByRole("button", { name: "Sign in" }).click();

    await page.waitForURL("**/app");
    expect(page.url()).not.toContain("evil.example");
  });

  test("an already-authenticated visitor to /login is redirected to /app", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/login");
    await page.waitForURL("**/app");
    await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0);
  });
});
