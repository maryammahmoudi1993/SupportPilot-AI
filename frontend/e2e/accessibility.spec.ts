import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

function seriousOrCritical(results: Awaited<ReturnType<AxeBuilder["analyze"]>>) {
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

test.describe("Accessibility (axe)", () => {
  test("/login has no serious/critical violations", async ({ page }) => {
    await page.goto("/login");
    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("authenticated /app has no serious/critical violations", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the no-workspace state has no serious/critical violations", async ({ page }) => {
    const data = e2eData();
    await login(page, data.zeroEmail, data.zeroPassword);
    await expect(page.getByText("No workspace is available for this account")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the SessionVerificationError state has no serious/critical violations", async ({ page }) => {
    await page.route("**/api/v1/auth/refresh/", (route) => route.abort("failed"));
    await page.route("**/api/v1/auth/csrf/", (route) => route.abort("failed"));
    await page.goto("/app");
    await expect(page.getByText("We couldn't verify your session")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });
});

test.describe("Keyboard-only pass", () => {
  test("login form is fully keyboard-operable", async ({ page }) => {
    const data = e2eData();
    await page.goto("/login");
    await page.getByLabel("Email").focus();
    await page.keyboard.type(data.primaryEmail);
    await page.keyboard.press("Tab");
    await page.keyboard.type(data.primaryPassword);
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeFocused();
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app");
  });

  test("workspace switcher and user menu are keyboard-operable", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    const switcher = page.getByRole("button", { name: data.defaultWorkspaceName });
    await switcher.focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(switcher).toBeFocused();

    const userMenu = page.getByRole("button", { name: /Account menu/i });
    await userMenu.focus();
    await page.keyboard.press("Enter");
    const signOut = page.getByRole("menuitem", { name: "Sign out" });
    await expect(signOut).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(userMenu).toBeFocused();
  });
});
