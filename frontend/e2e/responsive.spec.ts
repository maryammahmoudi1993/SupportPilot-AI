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
