import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 22 Chunk 2 real-backend smoke: Webhook Endpoints + Deliveries
 * (read-only — see features/webhooks/types.ts for the mutation-deferral
 * decision). Every scenario runs against the real Django API
 * (webhooks/views.py `WebhookEndpointListCreateView`/
 * `WebhookEndpointDetailView`/`WebhookDeliveryListView`/
 * `WebhookDeliveryDetailView`), never a mock. No live HTTP dispatch to any
 * real or fake destination is ever triggered by this suite (see
 * global-setup.ts's fixture-construction comment) — every delivery status
 * is reached through the real, pure-DB notifications.services functions.
 */
test.describe("Webhooks", () => {
  test("shows the real endpoint list and an active endpoint's real fields", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B.

    await page.goto("/app/integrations?tab=webhooks");
    await expect(page.getByRole("link", { name: "Webhooks" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.getByRole("link", { name: "Support ops relay" })).toBeVisible();

    await page.getByRole("link", { name: "Support ops relay" }).click();
    await expect(page.getByRole("heading", { name: "Support ops relay" })).toBeVisible();
    await expect(page.getByText("Active", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("https://example.com/hooks/supportpilot")).toBeVisible();
    await expect(page.getByText("Configured", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("approval.requested")).toBeVisible();
    await expect(page.getByText("handoff.created")).toBeVisible();
  });

  test("a disabled endpoint with no secret shows its real safe state", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/integrations/webhooks/${data.workspaceBWebhookEndpointDisabledId}`);
    await expect(page.getByRole("heading", { name: "Disabled relay" })).toBeVisible();
    await expect(page.getByText("Disabled", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Not configured", { exact: true }).first()).toBeVisible();
  });

  test("never renders the destination URL as a clickable link, and never leaks the signing secret", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/integrations/webhooks/${data.workspaceBWebhookEndpointId}`);
    await expect(page.getByRole("heading", { name: "Support ops relay" })).toBeVisible();
    await expect(page.getByRole("link", { name: /example\.com/i })).toHaveCount(0);

    const html = await page.content();
    expect(html).not.toMatch(/fake-signing-secret-not-real/);
    expect(html).not.toMatch(/encrypted_signing_secret/i);
    const storageDump = await page.evaluate(() => ({
      local: JSON.stringify(localStorage),
      session: JSON.stringify(sessionStorage),
    }));
    expect(storageDump.local).not.toMatch(/fake-signing-secret-not-real/);
    expect(storageDump.session).not.toMatch(/fake-signing-secret-not-real/);
  });

  test("shows the real delivery list with every real status rendered safely", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/app/integrations?tab=deliveries");
    await expect(page.getByRole("link", { name: "Deliveries" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.getByText("Delivered", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Pending", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Retry scheduled", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Dead", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Failed", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("In progress", { exact: true }).first()).toBeVisible();
  });

  test("a delivered delivery's real detail shows Settled, real attempt/HTTP status, and at-least-once honesty", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/integrations/deliveries/${data.workspaceBWebhookDeliveryDeliveredId}`);
    await expect(page.getByRole("heading", { name: "Human handoff created" })).toBeVisible();
    await expect(page.getByText("Delivered", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Settled")).toBeVisible();
    await expect(page.getByText("1 / 5")).toBeVisible();
    await expect(page.getByText("200", { exact: true })).toBeVisible();
    await expect(page.getByText("Next attempt")).toHaveCount(0);
    await expect(page.getByText(/at-least-once, never exactly-once/i)).toBeVisible();

    // Real cross-link back to the endpoint.
    await page.getByRole("link", { name: "Support ops relay" }).click();
    await expect(page.getByRole("heading", { name: "Support ops relay" })).toBeVisible();
  });

  test("a retry-scheduled delivery's real detail shows Still in progress and a real Next attempt", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(
      `/app/integrations/deliveries/${data.workspaceBWebhookDeliveryRetryScheduledId}`,
    );
    await expect(page.getByRole("heading", { name: "Approval requested" })).toBeVisible();
    await expect(page.getByText("Retry scheduled", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Still in progress")).toBeVisible();
    await expect(page.getByText("Next attempt")).toBeVisible();
    await expect(page.getByText("webhook_http_503")).toBeVisible();
  });

  test("a dead (non-retryable) delivery's real detail shows its real safe error code", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/integrations/deliveries/${data.workspaceBWebhookDeliveryDeadId}`);
    await expect(page.getByText("Dead", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Settled")).toBeVisible();
    await expect(page.getByText("webhook_invalid_url")).toBeVisible();
  });

  test("HTML/script-looking real endpoint name renders as inert text, never executed", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A.

    await page.goto(`/app/integrations/webhooks/${data.workspaceAWebhookEndpointId}`);
    await expect(page.getByText(/window\.__xss_marker = true;/)).toBeVisible();
    const marker = await page.evaluate(
      () => (window as unknown as { __xss_marker?: boolean }).__xss_marker,
    );
    expect(marker).not.toBe(true);
  });

  test("a foreign-workspace endpoint/delivery is never visible after a workspace switch", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; the endpoint/delivery below belong to A.
    await page.goto("/app/integrations?tab=webhooks");
    await expect(page.getByText(/window\.__xss_marker/)).toHaveCount(0);

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await expect(page.getByText(/window\.__xss_marker/)).toBeVisible();
  });

  test("a foreign-workspace endpoint deep link is safely rejected, never leaked", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; this endpoint belongs to A.

    await page.goto(`/app/integrations/webhooks/${data.workspaceAWebhookEndpointId}`);
    await expect(page.getByText("Webhook endpoint not found")).toBeVisible();

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/webhooks/endpoints/")),
      page.goto("/app/integrations?tab=webhooks"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    expect(authorization).toBeTruthy();
    const response = await page.request.get(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/webhooks/endpoints/${data.workspaceAWebhookEndpointId}/`,
      { headers: { Authorization: authorization } },
    );
    expect(response.status()).toBe(404);
    const body = await response.json();
    expect(body.error.code).toBe("not_found");
  });

  test("a foreign-workspace delivery deep link is safely rejected, never leaked", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; this delivery belongs to A.

    await page.goto(`/app/integrations/deliveries/${data.workspaceAWebhookDeliveryId}`);
    await expect(page.getByText("Webhook delivery not found")).toBeVisible();

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/webhooks/deliveries/")),
      page.goto("/app/integrations?tab=deliveries"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    expect(authorization).toBeTruthy();
    const response = await page.request.get(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/webhooks/deliveries/${data.workspaceAWebhookDeliveryId}/`,
      { headers: { Authorization: authorization } },
    );
    expect(response.status()).toBe(404);
    const body = await response.json();
    expect(body.error.code).toBe("not_found");
  });

  test("the endpoint and delivery lists issue no per-row detail request (no N+1)", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    const detailRequests: string[] = [];
    page.on("request", (req) => {
      if (
        /\/webhooks\/endpoints\/[0-9a-f-]{36}\/$/.test(req.url()) ||
        /\/webhooks\/deliveries\/[0-9a-f-]{36}\/$/.test(req.url())
      ) {
        detailRequests.push(req.url());
      }
    });

    await page.goto("/app/integrations?tab=webhooks");
    await expect(page.getByRole("link", { name: "Support ops relay" })).toBeVisible();
    await page.getByRole("link", { name: "Deliveries" }).click();
    await expect(page.getByText("Delivered", { exact: true }).first()).toBeVisible();
    await page.waitForTimeout(500);

    expect(detailRequests).toHaveLength(0);
  });

  test("logs out cleanly from Webhooks", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/app/integrations?tab=webhooks");
    await expect(page.getByRole("link", { name: "Support ops relay" })).toBeVisible();

    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
