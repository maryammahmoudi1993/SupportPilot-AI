import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 24 Chunk 3 real-backend smoke: Account (`GET /auth/me/`) — the one
 * real, public account capability confirmed by this chunk's contract
 * discovery. No new fixtures needed: uses the same real primary user and
 * real workspace memberships every other Phase 24 spec already relies on.
 */
test.describe("Account", () => {
  test("shows the real, already-fetched account email and every real workspace membership with its real role", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/app/settings/account");
    await expect(page.getByRole("heading", { name: "Account" })).toBeVisible();
    await expect(page.getByText(data.primaryEmail)).toBeVisible();

    const table = page.getByRole("table");
    await expect(table.getByText(data.defaultWorkspaceName)).toBeVisible();
    await expect(table.getByText(data.otherWorkspaceName)).toBeVisible();
    // Real roles: primary is owner in Workspace A, support_agent in Workspace B.
    await expect(table.getByText("Owner", { exact: true })).toBeVisible();
    await expect(table.getByText("Support Agent", { exact: true })).toBeVisible();
  });

  test("never renders any password/session/MFA control — none exist in the real contract", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/app/settings/account");
    await expect(page.getByRole("heading", { name: "Account" })).toBeVisible();

    await expect(page.getByLabel(/password/i)).toHaveCount(0);
    await expect(page.getByRole("button", { name: /change password/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /log out all sessions/i })).toHaveCount(0);
    await expect(page.getByText(/two-factor|multi-factor/i)).toHaveCount(0);
  });

  test("the Settings nav links between Members, Workspace, and Account as real, bookmarkable routes", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/app/settings/members");
    await page.getByRole("link", { name: "Account" }).click();
    await expect(page).toHaveURL(/\/app\/settings\/account$/);
    await expect(page.getByText(data.primaryEmail)).toBeVisible();
  });
});
