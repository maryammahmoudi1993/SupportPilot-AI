import path from "node:path";

import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

const VIEWPORTS = [
  { name: "mobile", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1280, height: 800 },
  { name: "large-desktop", width: 1440, height: 900 },
];

async function assertNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const overflow = await page.evaluate(() => {
    return document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
  });
  expect(overflow).toBe(false);
}

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.name} (${viewport.width}x${viewport.height})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test("/login has no horizontal overflow", async ({ page }) => {
      await page.goto("/login");
      await assertNoHorizontalOverflow(page);
    });

    test("/app has no horizontal overflow", async ({ page }) => {
      const data = e2eData();
      await login(page, data.primaryEmail, data.primaryPassword);
      await assertNoHorizontalOverflow(page);
    });

    // Phase 19 Chunk 4: the operational workspace's own list/detail pages.
    const OPERATIONAL_PAGES: {
      name: string;
      path: (data: ReturnType<typeof e2eData>) => string;
    }[] = [
      { name: "Customers list", path: () => "/app/customers" },
      { name: "Customer detail", path: (data) => `/app/customers/${data.workspaceBCustomerId}` },
      { name: "Inbox list", path: () => "/app/inbox" },
      {
        name: "Conversation detail",
        path: (data) => `/app/inbox/${data.workspaceBConversationId}`,
      },
      { name: "Tickets list", path: () => "/app/tickets" },
      { name: "Ticket detail", path: (data) => `/app/tickets/${data.workspaceBTicketId}` },
    ];

    for (const { name, path } of OPERATIONAL_PAGES) {
      test(`${name} has no horizontal overflow`, async ({ page }) => {
        const data = e2eData();
        await login(page, data.primaryEmail, data.primaryPassword);
        await page.goto(path(data));
        await expect(page.locator("table, h1, h2, h3").first()).toBeVisible();
        await assertNoHorizontalOverflow(page);
      });
    }

    // Phase 20 Chunk 4 (final acceptance gate, Part H §26): the AI-operations
    // surface, at every required viewport — Agent Runs/Approvals/Handoffs
    // list and detail pages, plus the execution trace embedded in Agent Run
    // detail. Approval/Handoff detail pages carry no h1/h2/h3 (see
    // accessibility.spec.ts's AI_OPERATIONS_PAGES), so each page's own
    // `role="status" aria-label="Loading ..."` region is the load signal.
    const AI_OPERATIONS_PAGES: {
      name: string;
      path: (data: ReturnType<typeof e2eData>) => string;
      loadingLabel: string;
    }[] = [
      {
        name: "Agent Runs list",
        path: () => "/app/agent-runs",
        loadingLabel: "Loading agent runs",
      },
      {
        name: "Agent Run detail (with execution trace)",
        path: (data) => `/app/agent-runs/${data.workspaceBAgentRunSucceededId}`,
        loadingLabel: "Loading agent run",
      },
      { name: "Approvals list", path: () => "/app/approvals", loadingLabel: "Loading approvals" },
      {
        name: "Approval detail",
        path: (data) => `/app/approvals/${data.workspaceBApprovalPendingId}`,
        loadingLabel: "Loading approval",
      },
      { name: "Handoffs list", path: () => "/app/handoffs", loadingLabel: "Loading handoffs" },
      {
        name: "Handoff detail",
        path: (data) => `/app/handoffs/${data.workspaceBHandoffPendingId}`,
        loadingLabel: "Loading handoff",
      },
    ];

    for (const { name, path, loadingLabel } of AI_OPERATIONS_PAGES) {
      test(`${name} has no horizontal overflow`, async ({ page }) => {
        const data = e2eData();
        await login(page, data.primaryEmail, data.primaryPassword);
        await page.goto(path(data));
        await expect(page.getByRole("status", { name: loadingLabel })).toBeHidden();
        await assertNoHorizontalOverflow(page);
      });
    }

    // Phase 21 Chunk 4 (final Knowledge/RAG acceptance gate, Part K §41):
    // Knowledge's list/tab/detail surfaces, at every required viewport.
    const KNOWLEDGE_PAGES: {
      name: string;
      path: (data: ReturnType<typeof e2eData>) => string;
    }[] = [
      { name: "Knowledge Documents list", path: () => "/app/knowledge" },
      { name: "Knowledge Sources tab", path: () => "/app/knowledge?tab=sources" },
      { name: "Knowledge Search tab", path: () => "/app/knowledge?tab=search" },
      {
        name: "Knowledge Document detail",
        path: (data) => `/app/knowledge/${data.workspaceBKnowledgeDocumentReadyId}`,
      },
    ];

    for (const { name, path } of KNOWLEDGE_PAGES) {
      test(`${name} has no horizontal overflow`, async ({ page }) => {
        const data = e2eData();
        await login(page, data.primaryEmail, data.primaryPassword);
        await page.goto(path(data));
        await expect(page.locator("table, h1, h2, h3, form").first()).toBeVisible();
        await assertNoHorizontalOverflow(page);
      });
    }

    // Phase 22 Chunk 4 (final integrations/webhook acceptance gate, Part L
    // §43): Integration Connection / Webhook Endpoint / Webhook Delivery
    // list/detail surfaces, at every required viewport.
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
        name: "Webhook delivery detail (failed, redrivable)",
        path: (data) => `/app/integrations/deliveries/${data.workspaceBWebhookDeliveryFailedId}`,
      },
    ];

    for (const { name, path } of INTEGRATION_WEBHOOK_PAGES) {
      test(`${name} has no horizontal overflow`, async ({ page }) => {
        const data = e2eData();
        await login(page, data.primaryEmail, data.primaryPassword);
        await page.goto(path(data));
        await expect(page.locator("table, h1, h2, h3, form").first()).toBeVisible();
        await assertNoHorizontalOverflow(page);
      });
    }
  });
}

test.describe("Mobile shell (375px)", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("desktop sidebar is hidden, mobile nav trigger works, drawer is fully accessible", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // The desktop sidebar (`aside`) is present in the DOM but hidden via
    // `hidden md:flex` at this width — assert it's not visible, not absent.
    await expect(page.getByRole("complementary", { name: "Sidebar" })).toBeHidden();

    const trigger = page.getByRole("button", { name: "Open navigation menu" });
    await expect(trigger).toBeVisible();
    await trigger.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("link", { name: "Overview" })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();

    // Workspace switcher and user menu (sign-out) remain reachable in the header.
    await expect(page.getByRole("button", { name: data.defaultWorkspaceName })).toBeVisible();
    await expect(page.getByRole("button", { name: /Account menu/i })).toBeVisible();
  });

  test("Customers is usable: list, search, and detail with related panels all reachable", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/customers");

    await expect(page.getByLabel("Search")).toBeVisible();
    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toBeVisible();

    await page.goto(`/app/customers/${data.workspaceBCustomerId}`);
    await expect(page.getByRole("heading", { name: data.workspaceBCustomerName })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Related conversations" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Related tickets" })).toBeVisible();
    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toBeVisible();
  });

  test("Inbox is usable: list opens a conversation whose timeline wraps long content and links back", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/inbox");
    await expect(
      page.getByRole("link", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();

    await page.getByRole("link", { name: data.workspaceBConversationSubject }).click();
    await page.waitForURL(`**/app/inbox/${data.workspaceBConversationId}`);
    await expect(
      page.getByRole("heading", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();
    await expect(page.getByText("My order hasn't arrived yet.")).toBeVisible();
    await assertNoHorizontalOverflow(page);

    await expect(
      page.getByRole("link", { name: `Customer #${data.workspaceBCustomerId.slice(0, 8)}` }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "← Back to Inbox" })).toBeVisible();
  });

  test("Tickets is usable: list opens a detail record with visible status and reachable links", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/tickets");
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toBeVisible();

    await page.getByRole("link", { name: data.workspaceBTicketSubject }).click();
    await page.waitForURL(`**/app/tickets/${data.workspaceBTicketId}`);
    await expect(page.getByRole("heading", { name: data.workspaceBTicketSubject })).toBeVisible();
    await expect(page.getByText("Urgent")).toBeVisible();
    await expect(
      page.getByRole("link", { name: `Customer #${data.workspaceBCustomerId.slice(0, 8)}` }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "View originating conversation" })).toBeVisible();
  });

  // Phase 20 Chunk 4 (final acceptance gate, Part H §27): at 375px, the
  // execution trace's structured payload viewer is usable, long values
  // scroll internally (not the page), and status/timestamps/cross-links
  // stay readable/reachable.
  test("Agent Run detail's execution trace is usable: structured payload readable, long values scroll internally, cross-links reachable", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);

    await expect(page.getByText("Succeeded", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Tool executions" })).toBeVisible();
    await expect(page.getByRole("link", { name: "View originating conversation" })).toBeVisible();
    await expect(page.getByRole("link", { name: "View related ticket" })).toBeVisible();

    // The real echo tool execution's redacted arguments/result — StructuredPayload
    // defaults open, so its <pre> (own overflow-auto, bounded max-height) is
    // already visible; assert it, not the page, is the scrolling container.
    const argumentsPayload = page.getByText(/"message": "hello"/);
    await expect(argumentsPayload).toBeVisible();
    const overflowsInternally = await argumentsPayload.evaluate((el) => {
      const style = getComputedStyle(el);
      return style.overflow === "auto" || style.overflowX === "auto";
    });
    expect(overflowsInternally).toBe(true);
    await assertNoHorizontalOverflow(page);
  });

  // Phase 20 Chunk 4 (final acceptance gate, Part H §28): at 375px, the
  // frozen Approval payload is readable, Approve/Reject are reachable, and
  // pending/decided state is visible.
  test("Approval detail is usable: frozen payload readable, Approve/Reject reachable, decision result visible", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(`/app/approvals/${data.workspaceAApprovalMobileId}`);
    await expect(page.getByText("Pending", { exact: true })).toBeVisible();
    await expect(page.getByText(/"amount_minor": 10000/)).toBeVisible();

    const rejectButton = page.getByRole("button", { name: "Reject" });
    await expect(rejectButton).toBeVisible();
    await rejectButton.click();

    await expect(page.getByText("Rejected", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject" })).toHaveCount(0);
    await assertNoHorizontalOverflow(page);
  });

  // Phase 21 Chunk 4 (final Knowledge/RAG acceptance gate, Part K §43): at
  // 375px, every real control on the upload form remains usable.
  test("Knowledge upload form is usable: Source/Title/File/Upload all reachable, error states readable", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/knowledge");
    await page.getByRole("button", { name: "Upload document" }).click();

    const form = page.getByRole("form", { name: "Upload a knowledge document" });
    await expect(form.getByLabel("Source")).toBeVisible();
    await expect(form.getByLabel("Title")).toBeVisible();
    await expect(form.getByLabel("File")).toBeVisible();
    await expect(form.getByRole("button", { name: "Upload" })).toBeVisible();
    await assertNoHorizontalOverflow(page);

    await form.getByLabel("Source").selectOption(data.workspaceAKnowledgeSourceId);
    await form.getByLabel("Title").fill("Mobile upload check");
    await form
      .getByLabel("File")
      .setInputFiles(path.join(__dirname, "fixtures-data", "e2e-unsupported.exe"));
    await form.getByRole("button", { name: "Upload" }).click();

    await expect(page.getByText("This upload was rejected")).toBeVisible();
    await assertNoHorizontalOverflow(page);
  });

  // Phase 22 Chunk 4 (final integrations/webhook acceptance gate, Part L
  // §44): at 375px, credential inputs, the webhook one-time-secret-reveal
  // flow, and event-subscription checkboxes all remain usable without
  // clipping — and the raw secret is never left visible after dismissal.
  test("Webhook endpoint create form is usable at mobile width: fields, event subscriptions, and the one-time secret reveal are all readable and dismissable", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/integrations?tab=webhooks");
    await page.getByRole("button", { name: "New endpoint" }).click();

    const form = page.getByRole("form", { name: "New webhook endpoint" });
    await expect(form.getByLabel("Name")).toBeVisible();
    await expect(form.getByLabel("Destination URL")).toBeVisible();
    await expect(form.getByLabel(/approval requested/i)).toBeVisible();
    await assertNoHorizontalOverflow(page);

    await form.getByLabel("Name").fill("Mobile relay");
    await form.getByLabel("Destination URL").fill("https://example.com/hooks/e2e-mobile");
    await form.getByLabel(/approval requested/i).check();
    await form.getByRole("button", { name: "Create endpoint" }).click();

    const secretPanel = page.getByRole("alert", { name: "Webhook signing secret" });
    await expect(secretPanel).toBeVisible();
    await assertNoHorizontalOverflow(page);

    // The real button label carries a typographic apostrophe ("I’ve"), not
    // a straight one — matched by substring so this doesn't silently drift
    // out of sync with the component's copy again.
    await page.getByRole("button", { name: /saved this secret/i }).click();
    await expect(secretPanel).toBeHidden();
  });

  // Phase 22 Chunk 4 (final integrations/webhook acceptance gate, Part L
  // §44): a real credential-bearing provider's fields remain usable at
  // 375px, and a submitted secret is absent from the rendered page
  // afterwards. Uses credential ROTATION on the pre-seeded Workspace A
  // Google Calendar connection (`workspaceAIntegrationCalendarId`, created
  // once in `global-setup.ts`) rather than a new CREATE: every provider
  // slot `uniq_integration_conn_ws_provider` allows in Workspace A is
  // already claimed by the real-backend mutation spec's own connections
  // (demo_commerce/email/stripe) plus this pre-seeded calendar fixture, so
  // a fifth create in the same workspace would collide — the same class of
  // fixture collision documented as PHASE22-3-03 below.
  test("Credential rotation (Google Calendar) is usable at mobile width: fields readable, submitted secret never rendered back", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/integrations/${data.workspaceAIntegrationCalendarId}`);
    await page.getByRole("button", { name: "Rotate credentials" }).click();

    const rotateSecretField = page.getByLabel(/service account/i);
    await expect(rotateSecretField).toBeVisible();
    await assertNoHorizontalOverflow(page);

    await rotateSecretField.fill('{"type": "service_account", "project_id": "mobile-e2e"}');
    await page.getByRole("button", { name: "Rotate credentials" }).click();
    await expect(page.getByRole("dialog", { name: "Rotate credentials?" })).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: "Rotate credentials" }).click();

    await expect(page.getByRole("button", { name: "Rotate credentials" })).toBeVisible();
    await expect(page.getByText("mobile-e2e")).toHaveCount(0);
    await assertNoHorizontalOverflow(page);
  });

  // Phase 21 Chunk 4 (final Knowledge/RAG acceptance gate, Part K §42): at
  // 375px, the Search form, a real ranked result, its Similarity score, and
  // a long chunk all remain readable/usable, and the Document link is reachable.
  test("Knowledge search is usable: query/top_k/source controls, a real result, and a long chunk are all readable", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/knowledge?tab=search");

    const form = page.getByRole("form", { name: "Search knowledge" });
    await expect(form.getByLabel("Query")).toBeVisible();
    await expect(form.getByLabel("Results")).toBeVisible();
    await expect(form.getByLabel("Source")).toBeVisible();
    await form.getByLabel("Query").fill("duplicate payment refund");
    await form.getByRole("button", { name: "Search" }).click();

    const resultsRegion = page.getByRole("region", { name: "Search results" });
    await expect(resultsRegion.getByRole("list")).toBeVisible();
    const firstResult = resultsRegion.getByRole("listitem").first();
    await expect(firstResult.getByText(/^Similarity \d\.\d\d$/)).toBeVisible();
    await expect(firstResult.getByRole("link", { name: "Support Handbook" })).toBeVisible();
    await assertNoHorizontalOverflow(page);
  });
});

test.describe("Desktop layout", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("sidebar, header, and main content are all visible with no overlap", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    const sidebar = page.getByRole("complementary", { name: "Sidebar" });
    const header = page.getByRole("banner");
    const main = page.locator("#main-content");

    await expect(sidebar).toBeVisible();
    await expect(header).toBeVisible();
    await expect(main).toBeVisible();

    const sidebarBox = await sidebar.boundingBox();
    const mainBox = await main.boundingBox();
    expect(sidebarBox).not.toBeNull();
    expect(mainBox).not.toBeNull();
    // No horizontal overlap between the sidebar and main content.
    expect(sidebarBox!.x + sidebarBox!.width).toBeLessThanOrEqual(mainBox!.x + 1);
  });
});
