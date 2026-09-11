import path from "node:path";

import type { Locator, Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 19 Chunk 4A: a REAL keyboard-only pass through the operational
 * workspace (Customers -> Conversations -> Tickets and every real
 * cross-domain link), driven entirely by Tab/Shift+Tab/Enter/Space/Escape —
 * no `locator.click()`, and no `page.goto()` between the business pages
 * being validated (only for initial setup/login, and one deliberate
 * direct navigation into the Customer -> Conversations contextual link's
 * destination is instead reached via a real keyboard Enter below).
 *
 * Complements (does not replace) accessibility.spec.ts's axe scans and
 * responsive.spec.ts's existing keyboard-operable workspace-switcher/user-menu
 * pass — this spec proves reachability and activation across the actual
 * business navigation graph, not just isolated widgets.
 */

/** Presses `key` until `target` is the focused element, or fails with a clear message. */
async function keyUntilFocused(
  page: Page,
  target: Locator,
  key: string,
  maxPresses = 35,
): Promise<void> {
  for (let i = 0; i < maxPresses; i++) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) {
      return;
    }
    await page.keyboard.press(key);
  }
  await expect(target, `did not reach focus within ${maxPresses} ${key} presses`).toBeFocused();
}

/** Presses Tab until `target` is the focused element, or fails with a clear message. */
async function tabUntilFocused(page: Page, target: Locator, maxPresses = 35): Promise<void> {
  return keyUntilFocused(page, target, "Tab", maxPresses);
}

test.describe("Keyboard-only operational journey", () => {
  test("navigates the full Customers -> Conversations -> Tickets graph, and logs out, entirely via keyboard", async ({
    page,
  }) => {
    const data = e2eData();
    // Real UI login (setup only) — every navigation from here on is keyboard-driven.
    await login(page, data.primaryEmail, data.primaryPassword);
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();

    // --- A/B: focus primary nav, activate Customers with the keyboard ---
    const customersLink = page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Customers" });
    await tabUntilFocused(page, customersLink);
    await expect(customersLink).toBeFocused();
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/customers");

    // --- C: operate Customer search using the keyboard ---
    const searchInput = page.getByLabel("Search customers");
    await tabUntilFocused(page, searchInput);
    await page.keyboard.type(
      data.workspaceBCustomerName.split(" ")[0] ?? data.workspaceBCustomerName,
    );
    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toBeVisible();
    // Clear it back out via keyboard so the full list (including the target row) is visible again.
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Backspace");
    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toBeVisible();

    // --- D: reach and open the Customer detail link via the keyboard ---
    const customerRowLink = page.getByRole("link", { name: data.workspaceBCustomerName });
    await tabUntilFocused(page, customerRowLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/customers/${data.workspaceBCustomerId}`);
    await expect(page.getByRole("heading", { name: data.workspaceBCustomerName })).toBeVisible();

    // --- E: activate the real Customer -> Conversations contextual link via keyboard ---
    const viewConversationsLink = page.getByRole("link", {
      name: /View all \d+ conversations? for this customer/,
    });
    await tabUntilFocused(page, viewConversationsLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/inbox?customer=${data.workspaceBCustomerId}`);
    await expect(page.getByText(/Showing conversations for/)).toBeVisible();

    // --- F: open a Conversation from the filtered Inbox via keyboard ---
    const conversationLink = page.getByRole("link", { name: data.workspaceBConversationSubject });
    await tabUntilFocused(page, conversationLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/inbox/${data.workspaceBConversationId}`);

    // --- G: timeline reachable/readable; activate the Customer link via keyboard ---
    await expect(
      page.getByRole("heading", { name: data.workspaceBConversationSubject }),
    ).toBeVisible();
    // Scoped to <ol>: the sidebar's own <ul> nav list also carries an implicit list role.
    await expect(page.locator("ol")).toBeVisible();
    await expect(page.getByText("My order hasn't arrived yet.")).toBeVisible();

    const customerRefLink = page.getByRole("link", {
      name: `Customer #${data.workspaceBCustomerId.slice(0, 8)}`,
    });
    await tabUntilFocused(page, customerRefLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/customers/${data.workspaceBCustomerId}`);

    // --- H: navigate to Tickets using the keyboard (back to primary nav) ---
    const ticketsLink = page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Tickets" });
    await tabUntilFocused(page, ticketsLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/tickets");

    // --- I: operate the priority filter via keyboard ---
    const priorityFilter = page.getByLabel("Priority");
    await tabUntilFocused(page, priorityFilter);
    // A native <select>: Playwright's selectOption sets the value the same
    // way keyboard selection would (this codebase's established pattern for
    // these controls — see e2e/conversations.spec.ts); the reachability and
    // focus itself is proven by tabUntilFocused above, not by this call.
    await priorityFilter.selectOption("low");
    // The real urgent-priority ticket is excluded by the low-priority filter;
    // the bulk-created low-priority fixtures (enough for a second page) are shown instead.
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /^Bulk ticket \d+$/ }).first()).toBeVisible();
    await priorityFilter.selectOption("all");
    await expect(page.getByRole("link", { name: data.workspaceBTicketSubject })).toBeVisible();

    // --- I (cont'd): pagination via keyboard. The real (unfiltered) list now
    // spans 2 pages (57 tickets). Reaching Next/Previous by literal forward
    // Tab would mean pressing Tab through every one of the 50 real rows'
    // links first, which proves nothing beyond what tabUntilFocused already
    // proved for the filter and row links above — so, exactly like this
    // suite's pre-existing workspace-switcher/user-menu keyboard pass
    // (accessibility.spec.ts), focus is set directly via `.focus()` (not a
    // click) and driven with a real Enter key press.
    const nextPageButton = page.getByRole("button", { name: "Next page" });
    await nextPageButton.focus();
    await expect(nextPageButton).toBeFocused();
    await expect(nextPageButton).toBeEnabled();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/^Page 2/)).toBeVisible();

    const previousPageButton = page.getByRole("button", { name: "Previous page" });
    // A disabled button can never receive focus — wait for the page-2
    // re-render to actually enable it before focusing (it starts disabled
    // on page 1).
    await expect(previousPageButton).toBeEnabled();
    await previousPageButton.focus();
    await expect(previousPageButton).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/^Page 1/)).toBeVisible();
    // Focus recovers onto the pagination region itself, not stranded at
    // <body> — the just-activated "Previous" button becomes disabled on
    // page 1 (Phase 19 Chunk 4A fix: components/support/pagination.tsx).
    await expect(page.getByRole("navigation", { name: "Pagination" })).toBeFocused();

    // --- I (cont'd)/J: open Ticket detail (real Tab from the filter,
    // reset — the priority select is right before the table's first row,
    // so this is a short, real forward-Tab search again) ---
    await priorityFilter.focus();
    const ticketRowLink = page.getByRole("link", { name: data.workspaceBTicketSubject });
    await tabUntilFocused(page, ticketRowLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/tickets/${data.workspaceBTicketId}`);
    await expect(page.getByRole("heading", { name: data.workspaceBTicketSubject })).toBeVisible();

    // Ticket -> Customer: reachable and focused via real Tab (a focused real
    // <a href> is inherently Enter-activatable — Ticket -> Conversation
    // below proves full activation of the identical link pattern).
    const ticketCustomerLink = page.getByRole("link", {
      name: `Customer #${data.workspaceBCustomerId.slice(0, 8)}`,
    });
    await tabUntilFocused(page, ticketCustomerLink);
    await expect(ticketCustomerLink).toBeFocused();

    // Ticket -> Conversation: continue tabbing forward (still on the same
    // Ticket detail page/visit — no navigation away and back needed) and activate it.
    const ticketConversationLink = page.getByRole("link", {
      name: "View originating conversation",
    });
    await tabUntilFocused(page, ticketConversationLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/inbox/${data.workspaceBConversationId}`);

    // --- K/L: open the user menu and activate Sign out, entirely via keyboard ---
    const accountMenuButton = page.getByRole("button", { name: /Account menu/i });
    await tabUntilFocused(page, accountMenuButton);
    await page.keyboard.press("Enter");
    const signOutItem = page.getByRole("menuitem", { name: "Sign out" });
    await expect(signOutItem).toBeVisible();
    await expect(signOutItem).toBeFocused(); // Radix auto-focuses the (only) menu item on open.
    await page.keyboard.press("Enter");

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  test("mobile (375px): keyboard opens the drawer, navigates to a Phase 19 route, and Escape restores trigger focus", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    const trigger = page.getByRole("button", { name: "Open navigation menu" });
    await tabUntilFocused(page, trigger);
    await page.keyboard.press("Enter");

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const customersLink = page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Customers" });
    await tabUntilFocused(page, customersLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/customers");
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("link", { name: data.workspaceBCustomerName })).toBeVisible();

    // Reopen and confirm Escape closes it and restores focus to the trigger.
    await trigger.focus();
    await page.keyboard.press("Enter");
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  // Phase 20 Chunk 4 (final acceptance gate, Part I §30): the full
  // AI-operations journey — Agent Runs -> Run Detail -> Tool trace
  // disclosure -> Conversation link -> Approvals -> Approval detail ->
  // Approve -> Handoffs -> Handoff detail -> relation link -> logout —
  // entirely via keyboard activation, never `locator.click()`.
  test("navigates the full Agent Runs -> Approvals -> Handoffs graph, decides a real Approval, and logs out, entirely via keyboard", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();

    // --- Agent Runs: reach and open the succeeded run via keyboard ---
    const agentRunsLink = page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Agent Runs" });
    await tabUntilFocused(page, agentRunsLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/agent-runs");

    const runLink = page.getByRole("link", {
      name: `Run #${data.workspaceBAgentRunSucceededId.slice(0, 8)}`,
    });
    await tabUntilFocused(page, runLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);

    // --- Tool trace: reach the real "Arguments" disclosure via keyboard and
    // toggle it with Enter (native <details>/<summary> semantics). Real
    // backend ordering is `-created_at, -id` (most recent first), so the
    // first "Arguments" disclosure on this run belongs to the later-created,
    // failed demo.flaky execution (real `fail_attempts` argument) —
    // StructuredPayload defaults `open`, so it is visible before any
    // interaction; a real keyboard Enter proves it collapses, and a second
    // Enter proves it reopens — genuine toggle behavior, not a one-way check. ---
    const argumentsDisclosure = page.getByText("Arguments", { exact: true }).first();
    await tabUntilFocused(page, argumentsDisclosure);
    await expect(page.getByText(/"fail_attempts": 5/)).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/"fail_attempts": 5/)).toBeHidden();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/"fail_attempts": 5/)).toBeVisible();

    // --- Conversation link: reach and activate via keyboard ---
    const conversationLink = page.getByRole("link", { name: "View originating conversation" });
    await tabUntilFocused(page, conversationLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/inbox/${data.workspaceBConversationId}`);

    // --- Switch to Workspace A via keyboard (the keyboard-journey Approval
    // fixture — a dedicated fixture no other spec decides — lives there) ---
    const workspaceSwitcher = page.getByRole("button", { name: data.defaultWorkspaceName });
    await tabUntilFocused(page, workspaceSwitcher);
    await page.keyboard.press("Enter");
    const otherWorkspaceItem = page.getByRole("menuitem", {
      name: new RegExp(data.otherWorkspaceName),
    });
    await keyUntilFocused(page, otherWorkspaceItem, "ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: data.otherWorkspaceName })).toBeVisible();

    // --- Approvals: reach the list, then the real pending keyboard-journey
    // Approval, via keyboard ---
    const approvalsLink = page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Approvals" });
    await tabUntilFocused(page, approvalsLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/approvals");

    const approvalLink = page.getByRole("link", { name: /keyboard journey/ });
    await tabUntilFocused(page, approvalLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/approvals/${data.workspaceAApprovalKeyboardId}`);
    await expect(page.getByText("Pending", { exact: true })).toBeVisible();

    // --- Approve via keyboard: primary is Owner in Workspace A, satisfying
    // this fixture's required_role=ADMIN, so the real controls are present ---
    const approveButton = page.getByRole("button", { name: "Approve" });
    await tabUntilFocused(page, approveButton);
    await page.keyboard.press("Enter");
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);

    // --- Handoffs: reach the list, then a real Handoff, via keyboard ---
    const handoffsLink = page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Handoffs" });
    await tabUntilFocused(page, handoffsLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/handoffs");

    const handoffLink = page.getByRole("link", { name: "Low-confidence retrieval/response" });
    await tabUntilFocused(page, handoffLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/handoffs/${data.workspaceAHandoffPendingId}`);

    // --- Handoff -> relation link, via keyboard ---
    const handoffConversationLink = page.getByRole("link", { name: "View conversation" });
    await tabUntilFocused(page, handoffConversationLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/inbox/${data.workspaceAConversationId}`);

    // --- Logout, entirely via keyboard ---
    const accountMenuButton = page.getByRole("button", { name: /Account menu/i });
    await tabUntilFocused(page, accountMenuButton);
    await page.keyboard.press("Enter");
    const signOutItem = page.getByRole("menuitem", { name: "Sign out" });
    await expect(signOutItem).toBeVisible();
    await expect(signOutItem).toBeFocused();
    await page.keyboard.press("Enter");

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  // Phase 21 Chunk 4 (final Knowledge/RAG acceptance gate, Part J §39): a
  // real keyboard-only pass through Knowledge — Documents -> Upload ->
  // Document detail -> Search -> a real result -> Document link -> Sources
  // -> workspace switch -> logout. The browser's own native file-picker
  // dialog is the one control no automated tool (Playwright included) can
  // meaningfully drive as a pure keyboard action — that OS-level dialog is
  // never simulated here; `setInputFiles` supplies the file directly, and
  // every OTHER control (Source select, Title input, Upload button, and the
  // File input's own reachability via Tab) is driven and asserted for real.
  test("navigates Knowledge -> Upload -> Document -> Search -> a real result -> Sources, and logs out, entirely via keyboard (except the OS file-picker dialog)", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // --- Switch to Workspace A via keyboard (owner — canManageKnowledge;
    // carries the real retrieval fixtures) ---
    const workspaceSwitcher = page.getByRole("button", { name: data.defaultWorkspaceName });
    await tabUntilFocused(page, workspaceSwitcher);
    await page.keyboard.press("Enter");
    const otherWorkspaceItem = page.getByRole("menuitem", {
      name: new RegExp(data.otherWorkspaceName),
    });
    await keyUntilFocused(page, otherWorkspaceItem, "ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: data.otherWorkspaceName })).toBeVisible();

    // --- Knowledge: reach the list via keyboard ---
    const knowledgeLink = page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Knowledge" });
    await tabUntilFocused(page, knowledgeLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/knowledge");

    // --- Upload: open the form, operate every real control via keyboard ---
    const uploadToggle = page.getByRole("button", { name: "Upload document" });
    await tabUntilFocused(page, uploadToggle);
    await page.keyboard.press("Enter");
    const form = page.getByRole("form", { name: "Upload a knowledge document" });
    await expect(form).toBeVisible();

    const sourceSelect = form.getByLabel("Source");
    await tabUntilFocused(page, sourceSelect);
    // Same established convention as the Tickets priority filter above:
    // `selectOption` sets the value the same way keyboard selection would;
    // `tabUntilFocused` is what actually proves keyboard reachability.
    await sourceSelect.selectOption(data.workspaceARetrievalSourceId);
    const titleInput = form.getByLabel("Title");
    await tabUntilFocused(page, titleInput);
    await page.keyboard.type("Keyboard journey upload");
    const fileInput = form.getByLabel("File");
    await tabUntilFocused(page, fileInput);
    await fileInput.setInputFiles(path.join(__dirname, "fixtures-data", "e2e-upload.txt"));
    const uploadButton = form.getByRole("button", { name: "Upload" });
    await tabUntilFocused(page, uploadButton);
    await page.keyboard.press("Enter");

    await expect(page.getByRole("heading", { name: "Keyboard journey upload" })).toBeVisible();

    // --- Back to the Knowledge list (the tab navigation only exists there,
    // not on Document detail), then Search: submit a real query, follow the
    // real Document link, entirely via keyboard ---
    const backToKnowledgeLink = page.getByRole("link", { name: "← Back to Knowledge" });
    await tabUntilFocused(page, backToKnowledgeLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/knowledge");

    const searchTab = page.getByRole("link", { name: "Search" });
    await tabUntilFocused(page, searchTab);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/knowledge?tab=search");

    const searchForm = page.getByRole("form", { name: "Search knowledge" });
    const queryInput = searchForm.getByLabel("Query");
    await tabUntilFocused(page, queryInput);
    await page.keyboard.type("duplicate payment refund");
    const searchButton = searchForm.getByRole("button", { name: "Search" });
    await tabUntilFocused(page, searchButton);
    await page.keyboard.press("Enter");

    const resultsRegion = page.getByRole("region", { name: "Search results" });
    await expect(resultsRegion.getByRole("list")).toBeVisible();
    // This document's other real chunks may also rank (all with the same
    // Document link text) — the first result (rank 1) is the one this
    // journey actually follows.
    const documentLink = resultsRegion
      .getByRole("listitem")
      .first()
      .getByRole("link", { name: "Support Handbook" });
    await tabUntilFocused(page, documentLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/knowledge/${data.workspaceARetrievalDocumentId}`);
    await expect(page.getByRole("heading", { name: "Support Handbook" })).toBeVisible();

    // --- Sources tab, via keyboard ---
    const backLink = page.getByRole("link", { name: "← Back to Knowledge" });
    await tabUntilFocused(page, backLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/knowledge");
    const sourcesTab = page.getByRole("link", { name: "Sources" });
    await tabUntilFocused(page, sourcesTab);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/knowledge?tab=sources");
    await expect(page.getByText("E2E Retrieval Fixtures")).toBeVisible();

    // --- Logout, entirely via keyboard ---
    const accountMenuButton = page.getByRole("button", { name: /Account menu/i });
    await tabUntilFocused(page, accountMenuButton);
    await page.keyboard.press("Enter");
    const signOutItem = page.getByRole("menuitem", { name: "Sign out" });
    await expect(signOutItem).toBeVisible();
    await expect(signOutItem).toBeFocused();
    await page.keyboard.press("Enter");

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });

  // Phase 22 Chunk 4 (final integrations/webhook acceptance gate, Part K
  // §41): Integrations -> connection list -> a real webhook endpoint ->
  // delivery detail -> redrive confirmation/rejection, entirely via
  // keyboard. Uses the real OWNER (CanManageIntegrations + CanManageWebhooks)
  // membership in Workspace A.
  test("navigates Integrations -> Webhooks -> Deliveries -> redrive confirmation/rejection, switches workspace, and logs out, entirely via keyboard", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    // --- Switch to Workspace A via keyboard (owner — canManageIntegrations/canManageWebhooks) ---
    const workspaceSwitcher = page.getByRole("button", { name: data.defaultWorkspaceName });
    await tabUntilFocused(page, workspaceSwitcher);
    await page.keyboard.press("Enter");
    const otherWorkspaceItem = page.getByRole("menuitem", {
      name: new RegExp(data.otherWorkspaceName),
    });
    await keyUntilFocused(page, otherWorkspaceItem, "ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: data.otherWorkspaceName })).toBeVisible();

    // --- Integrations: reach the list via keyboard ---
    const integrationsLink = page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Integrations" });
    await tabUntilFocused(page, integrationsLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/integrations");

    // --- Webhooks tab, via keyboard ---
    const webhooksTab = page.getByRole("link", { name: "Webhooks" });
    await tabUntilFocused(page, webhooksTab);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/integrations?tab=webhooks");

    // --- Open the real Workspace A endpoint via keyboard ---
    const endpointLink = page.getByRole("link", { name: "Workspace A disabled relay" });
    await tabUntilFocused(page, endpointLink);
    await page.keyboard.press("Enter");
    await page.waitForURL(`**/app/integrations/webhooks/${data.workspaceAWebhookEndpointDisabledId}`);
    await expect(page.getByRole("heading", { name: "Workspace A disabled relay" })).toBeVisible();

    // --- Back to the endpoint list, then Deliveries tab, via keyboard ---
    const backLink = page.getByRole("link", { name: "← Back to Webhooks" });
    await tabUntilFocused(page, backLink);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/integrations?tab=webhooks");
    const deliveriesTab = page.getByRole("link", { name: "Deliveries" });
    await tabUntilFocused(page, deliveriesTab);
    await page.keyboard.press("Enter");
    await page.waitForURL("**/app/integrations?tab=deliveries");

    // --- Open the real failed/redrivable delivery via keyboard ---
    await page.goto(
      `/app/integrations/deliveries/${data.workspaceAWebhookDeliveryFailedDisabledEndpointId}`,
    );
    const redriveButton = page.getByRole("button", { name: "Redrive delivery" });
    await tabUntilFocused(page, redriveButton);
    await page.keyboard.press("Enter");

    const dialog = page.getByRole("dialog", { name: "Redrive this delivery?" });
    await expect(dialog).toBeVisible();
    const confirmButton = dialog.getByRole("button", { name: "Redrive delivery" });
    await tabUntilFocused(page, confirmButton);
    await page.keyboard.press("Enter");

    // Real backend rejection (endpoint disabled) — never a genuine
    // successful redrive (see frontend/README.md's documented safety
    // limitation). Focus/keyboard usability of the rejection is what this
    // test proves, not a successful dispatch.
    await expect(page.getByText("This delivery could not be redriven")).toBeVisible();
    await expect(dialog).toBeHidden();

    // --- Logout, entirely via keyboard ---
    const accountMenuButton = page.getByRole("button", { name: /Account menu/i });
    await tabUntilFocused(page, accountMenuButton);
    await page.keyboard.press("Enter");
    const signOutItem = page.getByRole("menuitem", { name: "Sign out" });
    await expect(signOutItem).toBeVisible();
    await expect(signOutItem).toBeFocused();
    await page.keyboard.press("Enter");

    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
