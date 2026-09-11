import path from "node:path";

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

  // Phase 21 Chunk 4 (final Knowledge/RAG acceptance gate, Part J §38): the
  // Knowledge domain's list/detail/tab surfaces, scanned separately since
  // no earlier chunk's report covered them with axe.
  const KNOWLEDGE_PAGES: { name: string; path: (data: ReturnType<typeof e2eData>) => string }[] = [
    { name: "Knowledge Documents list", path: () => "/app/knowledge" },
    { name: "Knowledge Sources tab", path: () => "/app/knowledge?tab=sources" },
    { name: "Knowledge Search tab", path: () => "/app/knowledge?tab=search" },
    {
      name: "Knowledge Document detail (ready)",
      path: (data) => `/app/knowledge/${data.workspaceBKnowledgeDocumentReadyId}`,
    },
    {
      name: "Knowledge Document detail (failed)",
      path: (data) => `/app/knowledge/${data.workspaceBKnowledgeDocumentFailedId}`,
    },
  ];

  for (const { name, path } of KNOWLEDGE_PAGES) {
    test(`${name} has no serious/critical violations`, async ({ page }) => {
      const data = e2eData();
      await login(page, data.primaryEmail, data.primaryPassword);
      await page.goto(path(data));
      await expect(page.locator("table, h1, h2, h3, form").first()).toBeVisible();

      const results = await new AxeBuilder({ page }).analyze();
      expect(
        seriousOrCritical(results),
        JSON.stringify(seriousOrCritical(results), null, 2),
      ).toEqual([]);
    });
  }

  test("Knowledge Document detail (actively processing, non-terminal) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/knowledge/${data.workspaceAKnowledgeDocumentProcessingId}`);
    await expect(page.getByText("Still in progress")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the Knowledge upload form (open, empty) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/knowledge");
    await page.getByRole("button", { name: "Upload document" }).click();
    await expect(page.getByRole("form", { name: "Upload a knowledge document" })).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("a real unsupported-file upload rejection has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/knowledge");
    await page.getByRole("button", { name: "Upload document" }).click();
    const form = page.getByRole("form", { name: "Upload a knowledge document" });
    await form.getByLabel("Source").selectOption(data.workspaceAKnowledgeSourceId);
    await form.getByLabel("Title").fill("Axe unsupported file");
    await form
      .getByLabel("File")
      .setInputFiles(path.join(__dirname, "fixtures-data", "e2e-unsupported.exe"));
    await form.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByText("This upload was rejected")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("a real zero-result Knowledge search has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/knowledge?tab=search");
    const form = page.getByRole("form", { name: "Search knowledge" });
    await form.getByLabel("Source").selectOption(data.workspaceAKnowledgeSourceId);
    await form.getByLabel("Query").fill("anything at all");
    await form.getByRole("button", { name: "Search" }).click();
    await expect(page.getByText("No results")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("a real Knowledge search with results has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/knowledge?tab=search");
    const form = page.getByRole("form", { name: "Search knowledge" });
    await form.getByLabel("Query").fill("duplicate payment refund");
    await form.getByRole("button", { name: "Search" }).click();
    await expect(page.getByRole("region", { name: "Search results" }).getByRole("list")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("a Knowledge Documents list network-error state has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.route("**/api/v1/workspaces/*/knowledge/documents/*", (route) =>
      route.abort("failed"),
    );
    await page.goto("/app/knowledge");
    await expect(page.getByText("Something went wrong")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  // Phase 22 Chunk 4 (final integrations/webhook acceptance gate, Part K
  // §40): Integration Connection / Webhook Endpoint / Webhook Delivery
  // list/detail surfaces, scanned with the real OWNER (CanManageIntegrations
  // + CanManageWebhooks) membership in Workspace A.
  const INTEGRATION_WEBHOOK_PAGES: {
    name: string;
    path: (data: ReturnType<typeof e2eData>) => string;
  }[] = [
    { name: "Integrations: connection list", path: () => "/app/integrations" },
    {
      name: "Integrations: connection detail (Stripe)",
      path: (data) => `/app/integrations/${data.workspaceBIntegrationStripeId}`,
    },
    { name: "Integrations: webhook endpoints tab", path: () => "/app/integrations?tab=webhooks" },
    {
      name: "Integrations: webhook endpoint detail",
      path: (data) => `/app/integrations/webhooks/${data.workspaceBWebhookEndpointId}`,
    },
    { name: "Integrations: deliveries tab", path: () => "/app/integrations?tab=deliveries" },
    {
      name: "Webhook delivery detail (non-terminal, pending)",
      path: (data) => `/app/integrations/deliveries/${data.workspaceBWebhookDeliveryPendingId}`,
    },
    {
      name: "Webhook delivery detail (failed, redrivable)",
      path: (data) => `/app/integrations/deliveries/${data.workspaceBWebhookDeliveryFailedId}`,
    },
  ];

  for (const { name, path } of INTEGRATION_WEBHOOK_PAGES) {
    test(`${name} has no serious/critical violations`, async ({ page }) => {
      const data = e2eData();
      await login(page, data.primaryEmail, data.primaryPassword);
      await page.goto(path(data));
      await expect(page.locator("table, h1, h2, h3, form").first()).toBeVisible();

      const results = await new AxeBuilder({ page }).analyze();
      expect(
        seriousOrCritical(results),
        JSON.stringify(seriousOrCritical(results), null, 2),
      ).toEqual([]);
    });
  }

  test("the connection create form (open) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/integrations");
    await page.getByRole("button", { name: "New connection" }).click();
    await expect(page.getByRole("form", { name: "New integration connection" })).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the credential-rotation form (open, on a real connection) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/integrations/${data.workspaceAIntegrationCalendarId}`);
    await page.getByRole("button", { name: "Rotate credentials" }).click();
    await expect(page.getByText("New credentials")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the webhook endpoint create form (open) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/integrations?tab=webhooks");
    await page.getByRole("button", { name: "New endpoint" }).click();
    await expect(page.getByRole("form", { name: "New webhook endpoint" })).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the redrive confirmation dialog (real failed delivery) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(
      `/app/integrations/deliveries/${data.workspaceAWebhookDeliveryFailedDisabledEndpointId}`,
    );
    await page.getByRole("button", { name: "Redrive delivery" }).click();
    await expect(page.getByRole("dialog", { name: "Redrive this delivery?" })).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  // Permission-denied/error state (master prompt Part K §40): the real
  // support_agent role in Workspace B has neither CanManageIntegrations nor
  // CanManageWebhooks — no mutation controls render at all, which is itself
  // the state under test here (RBAC is server-authoritative; the frontend's
  // read-only rendering must remain accessible on its own).
  test("Integrations surfaces for a role without manage permissions have no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B (support_agent) — no workspace switch.
    await page.goto(`/app/integrations/webhooks/${data.workspaceBWebhookEndpointId}`);
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Rotate signing secret" })).toHaveCount(0);

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
