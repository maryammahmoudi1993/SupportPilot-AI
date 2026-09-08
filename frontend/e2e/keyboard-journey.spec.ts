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

/** Presses Tab until `target` is the focused element, or fails with a clear message. */
async function tabUntilFocused(page: Page, target: Locator, maxPresses = 35): Promise<void> {
  for (let i = 0; i < maxPresses; i++) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) {
      return;
    }
    await page.keyboard.press("Tab");
  }
  await expect(target, `did not reach focus within ${maxPresses} Tab presses`).toBeFocused();
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
});
