import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 20 Chunk 1 real-backend smoke: Agent Runs + lifecycle visibility +
 * cross-domain navigation against the actual Django API. Full accessibility/
 * responsive acceptance is Chunk 4's job — this spec proves the real
 * contract end to end (see frontend/README.md, "Phase 20 test strategy").
 */
test.describe("Agent Runs", () => {
  test("lists the active workspace's real agent runs, filters by status, and opens one to see real fields", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // Default active workspace after login is Workspace B (see fixtures.ts).
    await page.getByRole("link", { name: "Agent Runs" }).click();
    await page.waitForURL("**/app/agent-runs");

    await expect(
      page.getByRole("link", { name: `Run #${data.workspaceBAgentRunSucceededId.slice(0, 8)}` }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: `Run #${data.workspaceAAgentRunId.slice(0, 8)}` }),
    ).toHaveCount(0);

    await page.getByLabel("Status").selectOption("running");
    await expect(
      page.getByRole("link", { name: `Run #${data.workspaceBAgentRunRunningId.slice(0, 8)}` }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: `Run #${data.workspaceBAgentRunSucceededId.slice(0, 8)}` }),
    ).toHaveCount(0);
    await page.getByLabel("Status").selectOption("all");

    await page
      .getByRole("link", { name: `Run #${data.workspaceBAgentRunSucceededId.slice(0, 8)}` })
      .click();
    await page.waitForURL(`**/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);

    await expect(
      page.getByRole("heading", { name: `Run #${data.workspaceBAgentRunSucceededId.slice(0, 8)}` }),
    ).toBeVisible();
    await expect(page.getByText("Your refund has been processed.")).toBeVisible();
    await expect(page.getByText("run_started")).toBeVisible();
    await expect(page.getByText("run_completed")).toBeVisible();
  });

  test("navigates Agent Run -> Conversation and Agent Run -> Ticket using real relationships", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);

    await page.getByRole("link", { name: "View originating conversation" }).click();
    await page.waitForURL(`**/app/inbox/${data.workspaceBConversationId}`);
    await expect(
      page.getByRole("heading", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();

    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);
    await page.getByRole("link", { name: "View related ticket" }).click();
    await page.waitForURL(`**/app/tickets/${data.workspaceBTicketId}`);
    await expect(page.getByRole("heading", { name: data.workspaceBTicketSubject })).toBeVisible();
  });

  test("a run created manually (no conversation/ticket) shows the honest no-relation notes", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunRunningId}`);

    await expect(
      page.getByRole("heading", { name: `Run #${data.workspaceBAgentRunRunningId.slice(0, 8)}` }),
    ).toBeVisible();
    await expect(page.getByText(/not tied to a conversation/)).toBeVisible();
    await expect(page.getByText(/not tied to a ticket/)).toBeVisible();
    await expect(
      page.getByRole("link", { name: "View originating conversation" }),
    ).toHaveCount(0);
  });

  test("switching workspaces swaps the agent run list — the old workspace's run is never shown", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/agent-runs");
    await expect(
      page.getByRole("link", { name: `Run #${data.workspaceBAgentRunSucceededId.slice(0, 8)}` }),
    ).toBeVisible();

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await expect(
      page.getByRole("link", { name: `Run #${data.workspaceAAgentRunId.slice(0, 8)}` }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: `Run #${data.workspaceBAgentRunSucceededId.slice(0, 8)}` }),
    ).toHaveCount(0);
  });

  test("an agent run ID from a different workspace is rejected as not-found, never leaked", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B; deep-link straight to A's run.
    await page.goto(`/app/agent-runs/${data.workspaceAAgentRunId}`);

    await expect(page.getByText("Agent run not found")).toBeVisible();
    await expect(page.getByText(data.workspaceAAgentRunResponse)).toHaveCount(0);
  });

  test("logs out cleanly from Agent Runs", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/agent-runs");
    await expect(
      page.getByRole("link", { name: `Run #${data.workspaceBAgentRunSucceededId.slice(0, 8)}` }),
    ).toBeVisible();

    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
