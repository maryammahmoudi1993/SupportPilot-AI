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
