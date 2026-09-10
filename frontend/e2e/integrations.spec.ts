import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 22 Chunk 1 real-backend smoke: Integration Connections (read-only —
 * see features/integrations/types.ts for the mutation-deferral decision).
 * Every scenario runs against the real Django API
 * (integrations/views.py `IntegrationConnectionListCreateView`/
 * `IntegrationConnectionDetailView`), never a mock. Workspace B's primary
 * membership is `support_agent`; Workspace A's is `owner` — both are
 * read-only for this chunk (no manage UI exists yet), so no RBAC-controls
 * test is needed here beyond proving nothing sensitive ever leaks to either.
 */
test.describe("Integrations", () => {
  test("shows the real connection list and an active connection's real fields", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B.

    await page.goto("/app/integrations");
    await expect(page.getByRole("heading", { name: "Integrations" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Primary Stripe" })).toBeVisible();

    await page.getByRole("link", { name: "Primary Stripe" }).click();
    await expect(page.getByRole("heading", { name: "Primary Stripe" })).toBeVisible();
    await expect(page.getByText("Active", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Configured", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("payment_lookup, refund")).toBeVisible();
  });

  test("a disabled connection with no credentials shows its real safe state", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/integrations/${data.workspaceBIntegrationEmailId}`);
    await expect(page.getByRole("heading", { name: "Email notifications" })).toBeVisible();
    await expect(page.getByText("Disabled", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Not configured", { exact: true }).first()).toBeVisible();
  });

  test("HTML/script-looking real configuration renders as inert text, never executed", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A.

    await page.goto(`/app/integrations/${data.workspaceAIntegrationCalendarId}`);
    await page.getByText("View configuration").click();
    await expect(page.getByText(/window\.__xss_marker = true;/)).toBeVisible();
    const marker = await page.evaluate(
      () => (window as unknown as { __xss_marker?: boolean }).__xss_marker,
    );
    expect(marker).not.toBe(true);
    // Real invalid-credentials status and safe error code render as text too.
    await expect(page.getByText("Invalid credentials", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("integration_invalid_credentials")).toBeVisible();
  });

  test("never renders raw credential material anywhere in the page", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/integrations/${data.workspaceBIntegrationStripeId}`);
    await expect(page.getByRole("heading", { name: "Primary Stripe" })).toBeVisible();
    const html = await page.content();
    expect(html).not.toMatch(/sk_test_fake_not_a_real_secret/);
    expect(html).not.toMatch(/encrypted_credentials/i);

    const storageDump = await page.evaluate(() => ({
      local: JSON.stringify(localStorage),
      session: JSON.stringify(sessionStorage),
    }));
    expect(storageDump.local).not.toMatch(/sk_test_fake_not_a_real_secret/);
    expect(storageDump.session).not.toMatch(/sk_test_fake_not_a_real_secret/);
    expect(page.url()).not.toMatch(/sk_test_fake_not_a_real_secret/);
  });

  test("a foreign-workspace connection is never visible after a workspace switch", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; this connection belongs to A.
    await page.goto("/app/integrations");
    await expect(page.getByText("Workspace A calendar")).toHaveCount(0);

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await expect(page.getByRole("link", { name: "Workspace A calendar" })).toBeVisible();
  });

  test("a foreign-workspace connection deep link is safely rejected, never leaked", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; this connection belongs to A.

    await page.goto(`/app/integrations/${data.workspaceAIntegrationCalendarId}`);
    await expect(page.getByText("Integration connection not found")).toBeVisible();

    // Independently, a direct API call under B is also safely rejected —
    // real backend authority, not just a client-side route guard (same
    // pattern as knowledge.spec.ts's equivalent check).
    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/integrations/")),
      page.goto("/app/integrations"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    expect(authorization).toBeTruthy();
    const response = await page.request.get(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/integrations/${data.workspaceAIntegrationCalendarId}/`,
      { headers: { Authorization: authorization } },
    );
    expect(response.status()).toBe(404);
    const body = await response.json();
    expect(body.error.code).toBe("not_found");
  });

  test("the connection list issues no per-row detail request (no N+1)", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    const detailRequests: string[] = [];
    page.on("request", (req) => {
      if (/\/integrations\/[0-9a-f-]{36}\/$/.test(req.url())) {
        detailRequests.push(req.url());
      }
    });

    await page.goto("/app/integrations");
    await expect(page.getByRole("link", { name: "Primary Stripe" })).toBeVisible();
    await page.waitForTimeout(500);

    expect(detailRequests).toHaveLength(0);
  });
});
