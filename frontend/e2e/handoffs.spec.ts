import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 20 Chunk 3 real-backend smoke: Human Handoff — read-only this
 * chunk (master prompt Part G §31; see frontend/README.md). Every scenario
 * runs against the real Django API (tickets/views.py `HumanHandoffListView`/
 * `HumanHandoffDetailView`), never a mock.
 */
test.describe("Human Handoff", () => {
  test("shows the real handoff queue and a real handoff's reason/status/links", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B.

    await page.goto("/app/handoffs");
    await expect(page.getByRole("heading", { name: "Handoffs" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Customer requested a human" })).toBeVisible();

    await page.getByRole("link", { name: "Customer requested a human" }).click();
    await expect(page.getByRole("heading", { name: "Customer requested a human" })).toBeVisible();
    await expect(page.getByText("Pending", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "View conversation" })).toHaveAttribute(
      "href",
      `/app/inbox/${data.workspaceBUnassignedConversationId}`,
    );
  });

  test("a resolved handoff links to its real Ticket and shows its real assignee", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/handoffs/${data.workspaceBHandoffResolvedId}`);
    await expect(page.getByText("Resolved", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "View related ticket" })).toHaveAttribute(
      "href",
      `/app/tickets/${data.workspaceBTicketId}`,
    );
  });

  test("a conversation's own handoff context is embedded in Conversation detail via the real conversation filter", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/inbox/${data.workspaceBUnassignedConversationId}`);
    await expect(page.getByRole("heading", { name: "Human handoff" })).toBeVisible();
    await expect(page.getByText("Customer requested a human")).toBeVisible();
  });

  test("a conversation's resolved (non-active) handoff still shows — real rows, not just 'active only'", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/inbox/${data.workspaceBConversationId}`);
    await expect(page.getByRole("heading", { name: "Human handoff" })).toBeVisible();
    await expect(page.getByText("Business workflow requires an operator")).toBeVisible();
  });

  test("a foreign-workspace handoff is never visible after a workspace switch", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; the handoff below belongs to A.
    await page.goto("/app/handoffs");
    await expect(page.getByText("Retrieval confidence was too low to answer safely.")).toHaveCount(
      0,
    );

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await expect(
      page.getByRole("link", { name: "Low-confidence retrieval/response" }),
    ).toBeVisible();
  });

  test("never offers an Assign or Resolve action — read-only this chunk", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/handoffs/${data.workspaceBHandoffPendingId}`);
    await expect(page.getByRole("button", { name: /^assign$/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^resolve$/i })).toHaveCount(0);
  });
});
