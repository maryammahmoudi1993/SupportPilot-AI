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

  test("the SessionVerificationError state has no serious/critical violations", async ({
    page,
  }) => {
    await page.route("**/api/v1/auth/refresh/", (route) => route.abort("failed"));
    await page.route("**/api/v1/auth/csrf/", (route) => route.abort("failed"));
    await page.goto("/app");
    await expect(page.getByText("We couldn't verify your session")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  // Phase 19 Chunk 4: the operational workspace's own list/detail pages,
  // scanned separately from the Phase 18 shell pages above.
  const OPERATIONAL_PAGES: { name: string; path: (data: ReturnType<typeof e2eData>) => string }[] =
    [
      { name: "Customers list", path: () => "/app/customers" },
      {
        name: "Customer detail",
        path: (data) => `/app/customers/${data.workspaceBCustomerId}`,
      },
      { name: "Inbox list", path: () => "/app/inbox" },
      {
        name: "Conversation detail",
        path: (data) => `/app/inbox/${data.workspaceBConversationId}`,
      },
      { name: "Tickets list", path: () => "/app/tickets" },
      {
        name: "Ticket detail",
        path: (data) => `/app/tickets/${data.workspaceBTicketId}`,
      },
    ];

  for (const { name, path } of OPERATIONAL_PAGES) {
    test(`${name} has no serious/critical violations`, async ({ page }) => {
      const data = e2eData();
      await login(page, data.primaryEmail, data.primaryPassword);
      await page.goto(path(data));
      // Wait for the real query to resolve so axe scans the loaded content,
      // not a transient skeleton — every one of these routes renders a
      // heading (list) or the record's own <h1>-equivalent (detail) once loaded.
      await expect(page.locator("table, h1, h2, h3").first()).toBeVisible();

      const results = await new AxeBuilder({ page }).analyze();
      expect(
        seriousOrCritical(results),
        JSON.stringify(seriousOrCritical(results), null, 2),
      ).toEqual([]);
    });
  }

  test("a network-error list state has no serious/critical violations", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.route("**/api/v1/workspaces/*/tickets/*", (route) => route.abort("failed"));
    await page.goto("/app/tickets");
    await expect(page.getByText("Something went wrong")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("an empty list state has no serious/critical violations", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Workspace A (switched into) has no Ticket seeded with priority "low"
    // matching this filter combination is unnecessary — the zero-Ticket
    // workspace state is reached directly via a status filter with no matches.
    await page.goto("/app/tickets");
    await page.getByLabel("Priority").selectOption("urgent");
    await page.getByLabel("Status").selectOption("closed");
    await expect(page.getByText("No tickets match your filters")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  // Phase 20 Chunk 4: the AI-operations surface (Agent Runs, Tool
  // Executions embedded in Agent Run detail, Approvals, Handoffs) — scanned
  // separately from the Phase 18/19 pages above, per the final acceptance
  // gate's explicit requirement (agent-runs.spec.ts and approvals.spec.ts
  // deliberately deferred full accessibility acceptance to this gate).
  const AI_OPERATIONS_PAGES: {
    name: string;
    path: (data: ReturnType<typeof e2eData>) => string;
    loadingLabel: string;
  }[] = [
    { name: "Agent Runs list", path: () => "/app/agent-runs", loadingLabel: "Loading agent runs" },
    {
      name: "Agent Run detail (succeeded)",
      path: (data) => `/app/agent-runs/${data.workspaceBAgentRunSucceededId}`,
      loadingLabel: "Loading agent run",
    },
    {
      name: "Agent Run detail (running, non-terminal, with a waiting tool execution)",
      path: (data) => `/app/agent-runs/${data.workspaceBAgentRunRunningId}`,
      loadingLabel: "Loading agent run",
    },
    { name: "Approvals list", path: () => "/app/approvals", loadingLabel: "Loading approvals" },
    {
      name: "Approval detail (pending)",
      path: (data) => `/app/approvals/${data.workspaceBApprovalPendingId}`,
      loadingLabel: "Loading approval",
    },
    { name: "Handoffs list", path: () => "/app/handoffs", loadingLabel: "Loading handoffs" },
    {
      name: "Handoff detail (pending)",
      path: (data) => `/app/handoffs/${data.workspaceBHandoffPendingId}`,
      loadingLabel: "Loading handoff",
    },
    {
      name: "Handoff detail (resolved)",
      path: (data) => `/app/handoffs/${data.workspaceBHandoffResolvedId}`,
      loadingLabel: "Loading handoff",
    },
  ];

  for (const { name, path, loadingLabel } of AI_OPERATIONS_PAGES) {
    test(`${name} has no serious/critical violations`, async ({ page }) => {
      const data = e2eData();
      await login(page, data.primaryEmail, data.primaryPassword);
      await page.goto(path(data));
      // Every one of these pages renders a role="status" region with this
      // exact aria-label only while its real query is pending — wait for it
      // to disappear so axe scans the loaded content, never a skeleton.
      await expect(page.getByRole("status", { name: loadingLabel })).toBeHidden();

      const results = await new AxeBuilder({ page }).analyze();
      expect(
        seriousOrCritical(results),
        JSON.stringify(seriousOrCritical(results), null, 2),
      ).toEqual([]);
    });
  }

  test("an expired Approval (non-actionable, terminal) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // The expired-approval fixture belongs to Workspace A (default active is B).
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(`/app/approvals/${data.workspaceAApprovalExpiredId}`);
    await expect(page.getByText("Expired", { exact: true })).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("an Agent Runs list network-error state has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.route("**/api/v1/workspaces/*/agent-runs/*", (route) => route.abort("failed"));
    await page.goto("/app/agent-runs");
    await expect(page.getByText("Something went wrong")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("a foreign-workspace Approval not-found state has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; this approval belongs to A — real 404.
    await page.goto(`/app/approvals/${data.workspaceAApprovalApproveId}`);
    await expect(page.getByText("Approval not found")).toBeVisible();

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
