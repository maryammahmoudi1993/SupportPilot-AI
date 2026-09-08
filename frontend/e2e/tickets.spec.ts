import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 19 Chunk 3 real-backend smoke: Tickets + cross-domain operational
 * navigation against the actual Django API. Full accessibility/responsive/
 * acceptance is Chunk 4's job — this spec proves the real contract end to
 * end (see frontend/README.md, "Phase 19 test strategy").
 */
test.describe("Tickets", () => {
  test("lists the active workspace's real tickets, filters by status, and opens one to see real fields", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // Default active workspace after login is Workspace B (see fixtures.ts).
    await page.getByRole("link", { name: "Tickets" }).click();
    await page.waitForURL("**/app/tickets");

    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toBeVisible();
    await expect(page.getByRole("link", { name: data.workspaceATicketSubject })).toHaveCount(0);

    await page.getByLabel("Status").selectOption("resolved");
    await expect(
      page.getByRole("link", { name: data.workspaceBResolvedTicketSubject }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toHaveCount(0);
    await page.getByLabel("Status").selectOption("all");

    await page.getByRole("link", { name: data.workspaceBTicketSubject }).click();
    await page.waitForURL(`**/app/tickets/${data.workspaceBTicketId}`);

    await expect(page.getByRole("heading", { name: data.workspaceBTicketSubject })).toBeVisible();
    await expect(page.getByText("Customer requests a refund.")).toBeVisible();
    await expect(page.getByText("Urgent")).toBeVisible();
  });

  test("navigates Ticket -> Customer and Ticket -> Conversation using real relationships", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/tickets/${data.workspaceBTicketId}`);

    await page
      .getByRole("link", { name: `Customer #${data.workspaceBCustomerId.slice(0, 8)}` })
      .click();
    await page.waitForURL(`**/app/customers/${data.workspaceBCustomerId}`);
    await expect(page.getByRole("heading", { name: data.workspaceBCustomerName })).toBeVisible();

    await page.goto(`/app/tickets/${data.workspaceBTicketId}`);
    await page.getByRole("link", { name: "View originating conversation" }).click();
    await page.waitForURL(`**/app/inbox/${data.workspaceBConversationId}`);
    await expect(
      page.getByRole("heading", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();
  });

  test("a ticket created directly (no conversation) shows the honest no-conversation note", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/tickets/${data.workspaceBResolvedTicketId}`);

    await expect(
      page.getByRole("heading", { name: data.workspaceBResolvedTicketSubject }),
    ).toBeVisible();
    await expect(page.getByText(/created directly, not from a conversation/)).toBeVisible();
    await expect(page.getByRole("link", { name: "View originating conversation" })).toHaveCount(0);
  });

  test("Customer detail links to real, filtered Tickets and Conversations for that customer", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/customers/${data.workspaceBCustomerId}`);

    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toBeVisible();
    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();

    await page.getByRole("link", { name: /View all \d+ tickets? for this customer/ }).click();
    await page.waitForURL(`**/app/tickets?customer=${data.workspaceBCustomerId}`);
    await expect(page.getByText(/Showing tickets for/)).toBeVisible();
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toBeVisible();
  });

  test("switching workspaces swaps the ticket list — the old workspace's ticket is never shown", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/tickets");
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toBeVisible();

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await expect(page.getByRole("link", { name: data.workspaceATicketSubject })).toBeVisible();
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toHaveCount(0);
  });

  test("a ticket ID from a different workspace is rejected as not-found, never leaked", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B; deep-link straight to A's ticket.
    await page.goto(`/app/tickets/${data.workspaceATicketId}`);

    await expect(page.getByText("Ticket not found")).toBeVisible();
    await expect(page.getByText(data.workspaceATicketSubject)).toHaveCount(0);
  });

  test("logs out cleanly from Tickets", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/tickets");
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toBeVisible();

    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
