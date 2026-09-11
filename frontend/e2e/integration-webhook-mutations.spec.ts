import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 22 Chunk 3 real-backend smoke: safe Integration Connection and
 * Webhook Endpoint mutations, and Webhook Delivery redrive (rejection
 * paths only — see the "Redrive" describe block below and
 * frontend/README.md for the documented safety limitation: a genuinely
 * *successful* redrive always schedules a real Celery dispatch
 * (`webhooks/services.py redrive_webhook_delivery`'s
 * `transaction.on_commit`), which this repository has no safe,
 * non-internet transport for).
 *
 * Every scenario runs against the real Django API, never a mock. The
 * primary user is a real OWNER in Workspace A (CanManageIntegrations +
 * CanManageWebhooks) and a real SUPPORT_AGENT in Workspace B (neither) —
 * this chunk deliberately reuses that existing real role split rather than
 * seeding new users, so both the authorized and unauthorized paths below
 * are proven against genuine RBAC, not a client-side assumption.
 */
test.describe("Integration Connection mutations", () => {
  test("creates a demo_commerce connection (no credentials/no network), edits it, tests it, and disables/re-enables it", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B (support_agent) — switch to A (owner).
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/integrations");
    await page.getByRole("button", { name: "New connection" }).click();
    await page.getByLabel("Display name (optional)").fill("E2E demo shop");
    await page.getByRole("button", { name: "Create connection" }).click();

    await expect(page.getByRole("heading", { name: "E2E demo shop" })).toBeVisible();
    await expect(page.getByText("Active", { exact: true }).first()).toBeVisible();

    // Edit.
    await page.getByRole("button", { name: "Edit" }).click();
    const nameInput = page.getByLabel("Display name");
    await nameInput.fill("E2E demo shop (renamed)");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("heading", { name: "E2E demo shop (renamed)" })).toBeVisible();

    // Test connection — demo_commerce's probe never touches the network
    // and always succeeds (integrations/providers/demo_commerce.py).
    await page.getByRole("button", { name: "Test connection" }).click();
    await expect(page.getByText("Connection test succeeded")).toBeVisible();

    // Disable, with confirmation, then re-enable.
    await page.getByRole("button", { name: "Disable connection" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Disable connection" })
      .click();
    await expect(page.getByRole("button", { name: "Enable connection" })).toBeVisible();
    await page.getByRole("button", { name: "Enable connection" }).click();
    await expect(page.getByRole("button", { name: "Disable connection" })).toBeVisible();
  });

  test("creates an email connection with real secret fields, then proves the submitted secret is never retained anywhere", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/integrations");
    await page.getByRole("button", { name: "New connection" }).click();
    await page.getByLabel("Provider").selectOption("email");
    await page.getByLabel("SMTP host").fill("smtp.example.com");
    await page.getByLabel("Username").fill("e2e-mutation-user");
    await page.getByLabel("Password").fill("e2e-mutation-password-not-real");
    await page.getByLabel("From address").fill("noreply@example.com");
    await page.getByRole("button", { name: "Create connection" }).click();

    // Wait for the real confirmed navigation to the created connection's
    // own detail page — never a pre-existing row's text, which would (and
    // initially did) pass instantly while the mutation was still pending.
    await expect(page.getByRole("heading", { name: "Email notifications" })).toBeVisible();

    const html = await page.content();
    expect(html).not.toMatch(/e2e-mutation-password-not-real/);
    const storageDump = await page.evaluate(() => ({
      local: JSON.stringify(localStorage),
      session: JSON.stringify(sessionStorage),
    }));
    expect(storageDump.local).not.toMatch(/e2e-mutation-password-not-real/);
    expect(storageDump.session).not.toMatch(/e2e-mutation-password-not-real/);
    expect(page.url()).not.toMatch(/e2e-mutation-password-not-real/);
  });

  test("never renders a manage control for the real support_agent role, and the backend independently denies a direct mutation", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace B — the primary user's real support_agent membership.

    await page.goto(`/app/integrations/${data.workspaceBIntegrationStripeId}`);
    await expect(page.getByRole("heading", { name: "Stripe" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /rotate credentials/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /disable connection/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /test connection/i })).toHaveCount(0);

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/integrations/")),
      page.goto("/app/integrations"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    expect(authorization).toBeTruthy();
    const response = await page.request.patch(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/integrations/${data.workspaceBIntegrationStripeId}/enabled/`,
      { headers: { Authorization: authorization }, data: { enabled: false } },
    );
    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.error.code).toBe("permission_denied");
  });
});

test.describe("Webhook Endpoint mutations", () => {
  test("creates an endpoint, reveals its signing secret exactly once, edits it, rotates its secret, and disables/re-enables it", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/integrations?tab=webhooks");
    await page.getByRole("button", { name: "New endpoint" }).click();
    await page.getByLabel("Name").fill("E2E mutation relay");
    // A structurally valid, globally-routable-but-inert destination — same
    // fixture URL convention as global-setup.ts. Creating an endpoint never
    // dispatches anything (only a delivery does), so this is safe.
    await page.getByLabel("Destination URL").fill("https://example.com/hooks/e2e-mutation");
    await page.getByLabel(/approval requested/i).check();
    await page.getByRole("button", { name: "Create endpoint" }).click();

    const createdSecretPanel = page.getByRole("alert", { name: "Webhook signing secret" });
    await expect(createdSecretPanel).toBeVisible();
    const firstSecret = await createdSecretPanel.getByRole("textbox").inputValue();
    expect(firstSecret.length).toBeGreaterThan(0);
    await createdSecretPanel.getByRole("button", { name: /saved this secret/i }).click();

    await expect(page.getByRole("heading", { name: "E2E mutation relay" })).toBeVisible();
    const html = await page.content();
    expect(html).not.toContain(firstSecret);

    // Edit.
    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Name").fill("E2E mutation relay (renamed)");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("heading", { name: "E2E mutation relay (renamed)" })).toBeVisible();

    // Rotate secret — a genuinely new value, never the same as the created one.
    await page.getByRole("button", { name: "Rotate signing secret" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Rotate secret" }).click();
    const rotatedSecretPanel = page.getByRole("alert", { name: "Webhook signing secret" });
    await expect(rotatedSecretPanel).toBeVisible();
    const rotatedSecret = await rotatedSecretPanel.getByRole("textbox").inputValue();
    expect(rotatedSecret).not.toBe(firstSecret);
    await rotatedSecretPanel.getByRole("button", { name: /saved this secret/i }).click();
    // Auto-retrying: waits for the dismissal's re-render to actually land,
    // rather than reading page.content() in the same tick as the click.
    await expect(rotatedSecretPanel).toHaveCount(0);
    const htmlAfterRotate = await page.content();
    expect(htmlAfterRotate).not.toContain(firstSecret);
    expect(htmlAfterRotate).not.toContain(rotatedSecret);

    // Disable/re-enable.
    await page.getByRole("button", { name: "Disable endpoint" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Disable endpoint" }).click();
    await expect(page.getByRole("button", { name: "Enable endpoint" })).toBeVisible();
    await page.getByRole("button", { name: "Enable endpoint" }).click();
    await expect(page.getByRole("button", { name: "Disable endpoint" })).toBeVisible();
  });

  test("never renders a manage control for the real support_agent role, and the backend independently denies a direct mutation", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace B — support_agent, not in WEBHOOK_MANAGE_ROLES.

    await page.goto(`/app/integrations/webhooks/${data.workspaceBWebhookEndpointId}`);
    await expect(page.getByRole("heading", { name: "Support ops relay" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /rotate signing secret/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /disable endpoint/i })).toHaveCount(0);

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/webhooks/endpoints/")),
      page.goto("/app/integrations?tab=webhooks"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    const response = await page.request.patch(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/webhooks/endpoints/${data.workspaceBWebhookEndpointId}/status/`,
      { headers: { Authorization: authorization }, data: { status: "disabled" } },
    );
    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.error.code).toBe("permission_denied");
  });
});

/**
 * Redrive is proven here only against its real, safe rejection paths — see
 * this file's module doc comment and frontend/README.md. A genuinely
 * successful redrive is never triggered against the real backend anywhere
 * in this suite.
 */
test.describe("Webhook Delivery redrive (rejection paths only)", () => {
  test("a real click-through redrive against a disabled endpoint is rejected before any dispatch, and the UI shows the real rejection honestly", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(
      `/app/integrations/deliveries/${data.workspaceAWebhookDeliveryFailedDisabledEndpointId}`,
    );
    await expect(page.getByText("Failed", { exact: true }).first()).toBeVisible();

    await page.getByRole("button", { name: "Redrive delivery" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Redrive delivery" }).click();

    await expect(page.getByText("This delivery could not be redriven")).toBeVisible();
    await expect(page.getByText("Delivery queued for another attempt.")).toHaveCount(0);
    // Still Failed — the UI never claimed a queued/success outcome for a rejected request.
    await expect(page.getByText("Failed", { exact: true }).first()).toBeVisible();
  });

  test("a direct redrive of a non-terminal delivery is rejected as not redrivable (invalid state)", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/webhooks/deliveries/")),
      page.goto("/app/integrations?tab=deliveries"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    const response = await page.request.post(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceAId}/webhooks/deliveries/${data.workspaceAWebhookDeliveryId}/redrive/`,
      { headers: { Authorization: authorization } },
    );
    // webhooks/errors.py WebhookError subclasses all inherit SafeAPIError's
    // default status_code (400) — never overridden to 409 — verified
    // directly against backend/webhooks/tests/test_redrive.py
    // test_redrive_on_not_redrivable_state_returns_safe_400.
    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body.error.code).toBe("webhook_delivery_not_redrivable");
  });

  test("a direct redrive attempt by the real support_agent role is denied", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace B — support_agent.

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/webhooks/deliveries/")),
      page.goto("/app/integrations?tab=deliveries"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    const response = await page.request.post(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/webhooks/deliveries/${data.workspaceBWebhookDeliveryFailedId}/redrive/`,
      { headers: { Authorization: authorization } },
    );
    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.error.code).toBe("permission_denied");
  });

  test("a foreign-workspace delivery redrive attempt resolves to not_found, never leaking its existence", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A; workspaceBWebhookDeliveryFailedId belongs to B.

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/webhooks/deliveries/")),
      page.goto("/app/integrations?tab=deliveries"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    const response = await page.request.post(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceAId}/webhooks/deliveries/${data.workspaceBWebhookDeliveryFailedId}/redrive/`,
      { headers: { Authorization: authorization } },
    );
    expect(response.status()).toBe(404);
    const body = await response.json();
    expect(body.error.code).toBe("not_found");
  });
});

test.describe("Mutation workspace isolation", () => {
  test("a connection created in Workspace A never appears in Workspace B, and a direct foreign-workspace fetch 404s", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/integrations");
    await page.getByRole("button", { name: "New connection" }).click();
    // A distinct provider (stripe) — Workspace A already has real
    // demo_commerce/email/google_calendar connections from earlier tests
    // in this file, and `uniq_integration_conn_ws_provider` allows only one
    // connection per (workspace, provider).
    await page.getByLabel("Provider").selectOption("stripe");
    await page.getByLabel("Secret key").fill("sk_test_e2e_isolation_not_a_real_secret");
    await page.getByLabel("Display name (optional)").fill("E2E isolation demo shop");
    await page.getByRole("button", { name: "Create connection" }).click();
    await expect(page.getByRole("heading", { name: "E2E isolation demo shop" })).toBeVisible();
    const createdUrl = page.url();
    const connectionId = createdUrl.split("/").pop() as string;

    // Switch to Workspace B — the connection must not appear, and a direct
    // fetch under B's workspace scope must 404, never leak existence.
    //
    // A client-side nav link click (never `page.goto`, a real hard
    // navigation) for the list check below: the auth session's real
    // coordinated single-use refresh-token rotation (SimpleJWT
    // `ROTATE_REFRESH_TOKENS`/blacklist, config/settings.py) can race if
    // two hard navigations fire back-to-back before the first one's
    // refresh cycle settles — caught during this chunk's own real-backend
    // run (see the Chunk 3 defect ledger). Reserving the one unavoidable
    // hard navigation for the direct connectionId deep-link below (no
    // `<Link>` exists for an arbitrary ID) keeps this test to a single hard
    // reload after the workspace switch, not two in immediate succession.
    await page.getByRole("button", { name: data.otherWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.defaultWorkspaceName) }).click();
    await page.getByRole("link", { name: "Integrations" }).click();
    await expect(page.getByRole("link", { name: "E2E isolation demo shop" })).toHaveCount(0);

    await page.goto(`/app/integrations/${connectionId}`);
    await expect(page.getByText("Integration connection not found")).toBeVisible();
  });
});
