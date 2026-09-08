import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 19 Chunk 2 real-backend smoke: Inbox/Conversations + message
 * timeline against the actual Django API. Full accessibility/responsive/
 * acceptance is Chunk 4's job — this spec proves the real contract end to
 * end (see frontend/README.md, "Phase 19 test strategy").
 */
test.describe("Inbox", () => {
  test("lists the active workspace's real conversations and opens one to see the real timeline", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // Default active workspace after login is Workspace B (see fixtures.ts).
    await page.getByRole("link", { name: "Inbox" }).click();
    await page.waitForURL("**/app/inbox");

    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: data.workspaceAConversationSubject }),
    ).toHaveCount(0);

    await page.getByRole("link", { name: data.workspaceBConversationSubject }).click();
    await page.waitForURL(`**/app/inbox/${data.workspaceBConversationId}`);

    await expect(
      page.getByRole("heading", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();
    // Real message timeline, real sender/source distinctions.
    await expect(page.getByText("My order hasn't arrived yet.")).toBeVisible();
    await expect(page.getByText("Tracking shows the package is out for delivery today.")).toBeVisible();
    await expect(page.getByText("Internal note")).toBeVisible();
  });

  test("status and assignment filters narrow the real result set", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/inbox");

    await page.getByLabel("Status").selectOption("closed");
    await expect(
      page.getByRole("link", { name: data.workspaceBUnassignedConversationSubject }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toHaveCount(0);

    await page.getByLabel("Status").selectOption("all");
    await page.getByLabel("Assignment").selectOption("unassigned");
    await expect(
      page.getByRole("link", { name: data.workspaceBUnassignedConversationSubject }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toHaveCount(0);
  });

  test("the linked customer opens the real customer detail page", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/inbox/${data.workspaceBConversationId}`);

    await page.getByRole("link", { name: `Customer #${data.workspaceBCustomerId.slice(0, 8)}` }).click();
    await page.waitForURL(`**/app/customers/${data.workspaceBCustomerId}`);
    await expect(page.getByRole("heading", { name: data.workspaceBCustomerName })).toBeVisible();
  });

  test("switching workspaces swaps the conversation list — the old workspace's conversation is never shown", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/inbox");
    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await expect(
      page.getByRole("link", { name: data.workspaceAConversationSubject }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toHaveCount(0);
  });

  test("a conversation ID from a different workspace is rejected as not-found, never leaked", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B; deep-link straight to A's conversation.
    await page.goto(`/app/inbox/${data.workspaceAConversationId}`);

    await expect(page.getByText("Conversation not found")).toBeVisible();
    await expect(page.getByText(data.workspaceAConversationSubject)).toHaveCount(0);
  });

  test("logs out cleanly from the inbox", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/inbox");
    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();

    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
