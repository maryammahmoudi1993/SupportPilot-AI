import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

test.describe("Workspace", () => {
  test("loads the real /auth/me/ workspace list and selects a deterministic active workspace", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await expect(page.getByRole("button", { name: data.defaultWorkspaceName })).toBeVisible();
  });

  test("switching workspaces via the real switcher updates the UI, persists, and survives a reload", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await expect(page.getByRole("button", { name: data.otherWorkspaceName })).toBeVisible();

    const persisted = await page.evaluate(() => localStorage.getItem("sp_active_workspace_id"));
    expect(persisted).toBe(data.otherWorkspaceId);

    await page.reload();
    await expect(page.getByRole("button", { name: data.otherWorkspaceName })).toBeVisible();
  });

  test("discards a stale/inaccessible persisted workspace ID and falls back safely, without crashing", async ({
    page,
  }) => {
    const data = e2eData();
    await page.goto("/login");
    await page.evaluate(() => {
      localStorage.setItem("sp_active_workspace_id", "00000000-0000-0000-0000-000000000000");
    });
    await page.getByLabel("Email").fill(data.primaryEmail);
    await page.getByLabel("Password").fill(data.primaryPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL("**/app");

    // Falls back to a real, accessible workspace — never stays on the
    // nonexistent stale ID, never crashes.
    await expect(page.getByRole("button", { name: data.defaultWorkspaceName })).toBeVisible();
    const persisted = await page.evaluate(() => localStorage.getItem("sp_active_workspace_id"));
    expect(persisted).not.toBe("00000000-0000-0000-0000-000000000000");
  });

  test("an authenticated user with zero workspace memberships sees an intentional no-workspace state, not a crash or a fake action", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.zeroEmail, data.zeroPassword);

    await expect(page.getByText("No workspace is available for this account")).toBeVisible();
    await expect(page.getByText("No workspace available")).toBeVisible(); // the switcher's own empty state
    await expect(page.getByRole("button", { name: /create workspace/i })).toHaveCount(0);
  });
});
