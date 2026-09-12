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

  // Phase 23 Chunk 4 (final Evaluations/Observability acceptance gate): the
  // Evaluations feature's list/tab/detail surfaces, scanned with the real
  // support_agent (read-only) membership in Workspace B first — the same
  // pattern as the Integrations block above.
  const EVALUATIONS_PAGES: { name: string; path: (data: ReturnType<typeof e2eData>) => string }[] =
    [
      { name: "Evaluations: run list", path: () => "/app/evaluations" },
      {
        name: "Evaluations: run detail (succeeded)",
        path: (data) => `/app/evaluations/${data.workspaceBEvaluationRunSucceededId}`,
      },
      {
        name: "Evaluations: run detail (running, non-terminal)",
        path: (data) => `/app/evaluations/${data.workspaceBEvaluationRunRunningId}`,
      },
      { name: "Evaluations: datasets tab", path: () => "/app/evaluations?tab=datasets" },
      {
        name: "Evaluations: dataset detail",
        path: (data) => `/app/evaluations/datasets/${data.workspaceBEvaluationDatasetId}`,
      },
    ];

  for (const { name, path } of EVALUATIONS_PAGES) {
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

  test("Evaluations run detail for a role without run permission has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B (support_agent, outside EVALUATION_RUN_ROLES).
    await page.goto(`/app/evaluations/${data.workspaceBEvaluationRunRunningId}`);
    await expect(page.getByRole("button", { name: "Cancel run" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Replay" })).toHaveCount(0);

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the New dataset form (open) has no serious/critical violations", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/evaluations?tab=datasets");
    await page.getByRole("button", { name: "New dataset" }).click();
    await expect(page.getByLabel("Name")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the Edit dataset form (open, real owner) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/evaluations/datasets/${data.workspaceAEvaluationDatasetId}`);
    await page.getByRole("button", { name: "Edit dataset" }).click();
    await expect(page.getByRole("form", { name: "Edit evaluation dataset" })).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the New case form (open) has no serious/critical violations", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/evaluations/datasets/${data.workspaceAEvaluationDatasetId}`);
    await page.getByRole("button", { name: "New case" }).click();
    await expect(page.getByLabel("Key")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the Edit case form (open, real case) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/evaluations/datasets/${data.workspaceAEvaluationDatasetId}`);
    await page.getByRole("button", { name: "Edit", exact: true }).first().click();
    await expect(page.getByLabel("Key")).toHaveCount(0);

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the Start run form (open, real published agent version) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/evaluations/datasets/${data.workspaceAEvaluationDatasetId}`);
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByLabel("Agent", { exact: true })).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the Cancel run confirmation dialog (real non-terminal run) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/evaluations/${data.workspaceAEvaluationRunRunningId}`);
    await page.getByRole("button", { name: "Cancel run" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("the Compare result view (real backend-computed comparison) has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/evaluations");

    const baselineRow = page.getByRole("row", {
      name: new RegExp(`Run #${data.workspaceAEvaluationRunId.slice(0, 8)}`),
    });
    const candidateRow = page.getByRole("row", {
      name: new RegExp(`Run #${data.workspaceAEvaluationRunRunningId.slice(0, 8)}`),
    });
    await baselineRow.getByRole("checkbox").check();
    await candidateRow.getByRole("checkbox").check();
    await page.getByRole("button", { name: /^Compare selected \(2\/2\)$/ }).click();
    await expect(page.getByText("Comparison result")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("an Evaluations run list network-error state has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.route("**/api/v1/workspaces/*/evaluations/runs/*", (route) =>
      route.abort("failed"),
    );
    await page.goto("/app/evaluations");
    await expect(page.getByText("Something went wrong")).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();
    expect(seriousOrCritical(results), JSON.stringify(seriousOrCritical(results), null, 2)).toEqual(
      [],
    );
  });

  test("renders unsafe-looking evaluation content inertly and still has no serious/critical violations", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/evaluations/datasets/${data.workspaceAEvaluationDatasetId}`);
    await expect(page.getByText("Unsafe content case")).toBeVisible();

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

  // Phase 23 Chunk 4 (final Evaluations/Observability acceptance gate): the
  // full Evaluations feature journey end to end, keyboard only — nav → runs
  // list → run detail → start run → cancel run → replay → compare →
  // datasets tab → dataset detail → case create/edit → back. Each control is
  // reached via `.focus()` (the same pattern the workspace-switcher/user-menu
  // test above uses) rather than a blind Tab sequence, since the DOM order of
  // rows/tables is a content-shaped implementation detail this test should
  // not depend on — what is asserted is that every step's control is a real
  // focusable, keyboard-operable element with visible focus, not that a
  // specific Tab count reaches it.
  test("the full Evaluations journey is keyboard-operable end to end with visible focus and no traps", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).focus();
    await page.keyboard.press("Enter");
    await page
      .getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) })
      .press("Enter");

    // Nav -> runs list, via the sidebar link.
    const evaluationsLink = page.getByRole("link", { name: "Evaluations" });
    await evaluationsLink.focus();
    await expect(evaluationsLink).toBeFocused();
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/evaluations");

    // Runs list -> run detail, via a real row link.
    const runLink = page.getByRole("link", {
      name: `Run #${data.workspaceAEvaluationRunRunningId.slice(0, 8)}`,
    });
    await runLink.focus();
    await expect(runLink).toBeFocused();
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/evaluations/${data.workspaceAEvaluationRunRunningId}`);

    // Run detail -> Cancel run dialog -> dismiss via Escape (no trap; focus
    // returns to a real, focusable element afterward) -> Replay.
    const cancelButton = page.getByRole("button", { name: "Cancel run" });
    await cancelButton.focus();
    await expect(cancelButton).toBeFocused();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    // No keyboard trap: focus lands back in the real document (never lost
    // to `<body>`, which is what a genuine trap would look like) once the
    // dialog unmounts. This intentionally doesn't pin to the literal same
    // trigger node — Radix's own focus-return target is an internal
    // implementation detail this test shouldn't encode as a hard
    // assertion, and the ConfirmDialog's own doc comment already states
    // that guarantee is Radix's responsibility, not this component's.
    const activeTag = await page.evaluate(() => document.activeElement?.tagName ?? null);
    expect(activeTag).not.toBe("BODY");

    await page.goto(`/app/evaluations/${data.workspaceAEvaluationRunId}`);
    const replayButton = page.getByRole("button", { name: "Replay" });
    await replayButton.focus();
    await expect(replayButton).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Replay queued as a new result.")).toBeVisible();

    // Runs list -> select two rows via keyboard (Space toggles a checkbox)
    // -> Compare selected.
    await page.goto("/app/evaluations");
    const baselineCheckbox = page
      .getByRole("row", { name: new RegExp(`Run #${data.workspaceAEvaluationRunId.slice(0, 8)}`) })
      .getByRole("checkbox");
    const candidateCheckbox = page
      .getByRole("row", {
        name: new RegExp(`Run #${data.workspaceAEvaluationRunRunningId.slice(0, 8)}`),
      })
      .getByRole("checkbox");
    await baselineCheckbox.focus();
    await page.keyboard.press("Space");
    await expect(baselineCheckbox).toBeChecked();
    await candidateCheckbox.focus();
    await page.keyboard.press("Space");
    await expect(candidateCheckbox).toBeChecked();
    const compareButton = page.getByRole("button", { name: /^Compare selected \(2\/2\)$/ });
    await compareButton.focus();
    await expect(compareButton).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Comparison result")).toBeVisible();

    // Datasets tab -> dataset detail -> New case -> fill and submit via
    // keyboard only -> Edit that case -> save via keyboard only -> back.
    const datasetsTab = page.getByRole("link", { name: "Datasets" });
    await datasetsTab.focus();
    await expect(datasetsTab).toBeFocused();
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/evaluations?tab=datasets");

    const datasetLink = page.getByRole("link", { name: data.workspaceAEvaluationDatasetName });
    await datasetLink.focus();
    await expect(datasetLink).toBeFocused();
    await page.keyboard.press("Enter");
    await page.waitForURL(/\/app\/evaluations\/datasets\/[0-9a-f-]+$/);

    const newCaseButton = page.getByRole("button", { name: "New case" });
    await newCaseButton.focus();
    await expect(newCaseButton).toBeFocused();
    await page.keyboard.press("Enter");
    const keyField = page.getByLabel("Key");
    await keyField.focus();
    await expect(keyField).toBeFocused();
    const caseKey = `e2e-kbd-case-${Date.now()}`;
    await page.keyboard.type(caseKey);
    await page.keyboard.press("Tab");
    await page.keyboard.type("Keyboard journey case");
    await page.getByLabel("Input message").focus();
    await page.keyboard.type("A real keyboard-created case's input.");
    const createCaseButton = page.getByRole("button", { name: "Create case" });
    await createCaseButton.focus();
    await expect(createCaseButton).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Keyboard journey case")).toBeVisible();

    const caseRow = page
      .getByRole("list", { name: "Evaluation cases in this dataset" })
      .getByRole("listitem")
      .filter({ hasText: "Keyboard journey case" });
    const editButton = caseRow.getByRole("button", { name: "Edit", exact: true });
    await editButton.focus();
    await expect(editButton).toBeFocused();
    await page.keyboard.press("Enter");
    const nameField = page.getByLabel("Name");
    await nameField.focus();
    await page.keyboard.press("Control+A");
    await page.keyboard.type("Keyboard journey case (updated)");
    const saveButton = page.getByRole("button", { name: "Save changes" });
    await saveButton.focus();
    await expect(saveButton).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Keyboard journey case (updated)")).toBeVisible();

    // Back to the runs list, via the sidebar nav link — end to end, no dead
    // ends. The Runs/Datasets tab strip only renders on the list page
    // itself (not on this dataset detail page), so the sidebar's own
    // "Evaluations" entry — the same real link used to enter the feature at
    // the top of this test — is the correct keyboard path back, and lands
    // on the list's default Runs tab.
    const backToEvaluations = page.getByRole("link", { name: "Evaluations" });
    await backToEvaluations.focus();
    await expect(backToEvaluations).toBeFocused();
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/evaluations");
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
