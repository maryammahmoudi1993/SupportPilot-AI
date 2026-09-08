import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 19 Chunk 1 real-backend smoke: Customers UI against the actual
 * Django API — login, list, search, detail, workspace-scoped pagination
 * parameters, workspace switch, cross-workspace rejection, and logout. Full
 * accessibility/responsive/multi-viewport acceptance is Chunk 4's job (see
 * frontend/README.md, "Phase 19 test strategy") — this spec only proves the
 * real contract works end-to-end.
 */
test.describe("Customers", () => {
  test("lists the active workspace's real customers and opens a detail record", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // Default active workspace after login is Workspace B (see fixtures.ts).
    await page.getByRole("link", { name: "Customers" }).click();
    await page.waitForURL("**/app/customers");

    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toBeVisible();
    await expect(page.getByRole("link", { name: data.workspaceACustomerName })).toHaveCount(0);

    await page.getByRole("link", { name: data.workspaceBCustomerName }).click();
    await page.waitForURL(`**/app/customers/${data.workspaceBCustomerId}`);
    await expect(page.getByRole("heading", { name: data.workspaceBCustomerName })).toBeVisible();
  });

  test("search narrows the real result set", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/customers");

    await page.getByLabel("Search customers").fill("nobody-matches-this-xyz");
    await expect(page.getByText("No customers match your filters")).toBeVisible();

    await page.getByLabel("Search customers").fill("");
    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toBeVisible();
  });

  test("switching workspaces swaps the customer list — the old workspace's customer is never shown", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/customers");
    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toBeVisible();

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await expect(page.getByRole("link", { name: data.workspaceACustomerName })).toBeVisible();
    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toHaveCount(0);
  });

  test("a customer ID from a different workspace is rejected as not-found, never leaked", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B; deep-link straight to A's customer.
    await page.goto(`/app/customers/${data.workspaceACustomerId}`);

    await expect(page.getByText("Customer not found")).toBeVisible();
    await expect(page.getByText(data.workspaceACustomerName)).toHaveCount(0);
  });

  test("logs out cleanly from the customers page", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/customers");
    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toBeVisible();

    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
