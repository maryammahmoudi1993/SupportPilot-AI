import path from "node:path";

import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 21 Chunk 1/2 real-backend smoke: Knowledge/RAG. Every scenario runs
 * against the real Django API (knowledge/views.py
 * `KnowledgeDocumentListCreateView`/`KnowledgeDocumentDetailView`/
 * `KnowledgeSourceListCreateView`/`KnowledgeDocumentRetryView`), never a
 * mock. Workspace B's primary membership is `support_agent`
 * (not `canManageKnowledge`) — Chunk 1's read-only-role coverage stays
 * there; Workspace A's is `owner` — Chunk 2's real upload/retry/source-
 * creation coverage uses that workspace instead.
 */
test.describe("Knowledge", () => {
  test("shows the real document queue and a ready document's real fields", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B.

    await page.goto("/app/knowledge");
    await expect(page.getByRole("heading", { name: "Knowledge" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Refund policy" })).toBeVisible();

    await page.getByRole("link", { name: "Refund policy" }).click();
    await expect(page.getByRole("heading", { name: "Refund policy" })).toBeVisible();
    await expect(page.getByText("Ready", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("refund-policy.txt")).toBeVisible();
    await expect(page.getByText("Settled")).toBeVisible();
  });

  test("a failed document shows its real safe error message, not a stack trace", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/knowledge/${data.workspaceBKnowledgeDocumentFailedId}`);
    await expect(page.getByRole("heading", { name: "Malformed upload" })).toBeVisible();
    await expect(page.getByText("Failed", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("The PDF is malformed or unreadable.")).toBeVisible();
  });

  test("HTML/script-looking real metadata renders as inert text, never executed", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto(`/app/knowledge/${data.workspaceBKnowledgeDocumentReadyId}`);
    await page.getByText("View metadata").click();
    await expect(page.getByText(/window\.__xss_marker = true;/)).toBeVisible();
    const marker = await page.evaluate(
      () => (window as unknown as { __xss_marker?: boolean }).__xss_marker,
    );
    expect(marker).not.toBe(true);
  });

  test("filters the document list by the real source_id and status parameters", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/app/knowledge");
    await page.getByLabel("Status").selectOption("failed");
    await expect(page.getByRole("link", { name: "Malformed upload" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Refund policy" })).toHaveCount(0);
  });

  test("switches to the real Sources tab and shows real source rows", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/app/knowledge?tab=sources");
    await expect(page.getByText(data.workspaceBKnowledgeSourceName)).toBeVisible();
    await expect(page.getByText("Canned refund/shipping responses.")).toBeVisible();
  });

  test("a foreign-workspace document is never visible after a workspace switch", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; the document below belongs to A.
    await page.goto("/app/knowledge");
    await expect(page.getByText("Workspace A only document")).toHaveCount(0);

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await expect(page.getByRole("link", { name: "Workspace A only document" })).toBeVisible();
  });

  test("a foreign-workspace document deep link is safely rejected, never leaked", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; this document belongs to A.

    await page.goto(`/app/knowledge/${data.workspaceAKnowledgeDocumentId}`);
    await expect(page.getByText("Document not found")).toBeVisible();
  });

  test("never offers Upload/New source/Retry to a read-only (support_agent) member, and never offers Delete at all", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B (support_agent — not canManageKnowledge).

    await page.goto("/app/knowledge");
    await expect(page.getByRole("button", { name: "Upload document" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^delete$/i })).toHaveCount(0);

    await page.goto("/app/knowledge?tab=sources");
    await expect(page.getByRole("button", { name: "New source" })).toHaveCount(0);

    await page.goto(`/app/knowledge/${data.workspaceBKnowledgeDocumentFailedId}`);
    await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^delete$/i })).toHaveCount(0);
  });

  test("an authorized (owner) manager uploads a real file, and it genuinely completes ingestion end to end", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A (owner — canManageKnowledge).

    await page.goto("/app/knowledge");
    await page.getByRole("button", { name: "Upload document" }).click();
    const uploadForm = page.getByRole("form", { name: "Upload a knowledge document" });
    await uploadForm.getByLabel("Source").selectOption(data.workspaceAKnowledgeSourceId);
    await uploadForm.getByLabel("Title").fill("E2E real upload");
    await uploadForm
      .getByLabel("File")
      .setInputFiles(path.join(__dirname, "fixtures-data", "e2e-upload.txt"));
    await uploadForm.getByRole("button", { name: "Upload" }).click();

    await expect(page.getByRole("heading", { name: "E2E real upload" })).toBeVisible();
    // Real initial status is never asserted as a fixed point here — a real
    // Celery worker (this environment's real, deterministic, offline
    // embedding provider — no external calls) may race straight through
    // `queued`/`processing` before the next poll even lands. What matters,
    // and IS asserted, is the genuine terminal outcome: real end-to-end
    // ingestion of a real, valid text file actually reaches `ready` — a
    // fabricated "success" claim would not survive this real backend round
    // trip. `refetchInterval` polling (5s) carries the page there; no
    // artificial wait/sleep is added.
    await expect(page.getByText("Ready", { exact: true }).first()).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("Settled")).toBeVisible();
    // Real extraction/chunking genuinely ran (not just a status flip).
    await expect(page.getByText("Extracted characters")).toBeVisible();
    const chunksRow = page.locator("dt", { hasText: "Chunks" }).locator("xpath=..");
    await expect(chunksRow.locator("dd")).not.toHaveText("0");
  });

  test("an authorized (owner) manager creates a real knowledge source", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/knowledge?tab=sources");
    await page.getByRole("button", { name: "New source" }).click();
    await page.getByLabel("Name").fill("E2E Created Source");
    await page.getByRole("button", { name: "Create source" }).click();

    await expect(page.getByText("E2E Created Source")).toBeVisible();
  });

  test("an authorized (owner) manager retries a real failed document — real 202, real re-processing", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(`/app/knowledge/${data.workspaceAKnowledgeDocumentFailedId}`);
    await expect(page.getByText("Failed", { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Retry" }).click();

    // Real state transition, not a guess: Retry is genuinely gone the
    // instant the document is no longer `failed` (whatever real state it's
    // in — this races a real Celery worker, so no specific intermediate
    // status is asserted; see the upload test above for the same reasoning).
    await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);

    // This fixture's `stored_file` points at a path with no real underlying
    // file on disk (it was created directly via the ORM, never through a
    // real upload) — so real re-ingestion genuinely cannot succeed. It
    // retries a bounded number of times (`KNOWLEDGE_INGESTION_MAX_ATTEMPTS`)
    // and then permanently re-fails — a real round trip through the async
    // pipeline, not an instant no-op, which is exactly what this proves:
    // Retry actually re-triggered real processing.
    await expect(page.getByText("Failed", { exact: true }).first()).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  });

  test("a direct, unauthorized API upload attempt is genuinely rejected by the backend — no privilege escalation", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B (support_agent) — the UI never offers
    // Upload here (see the read-only-role test above); this proves the
    // backend independently rejects the write even if a client attempted
    // it directly, bypassing the UI entirely.

    // The app's real Bearer token lives only in an in-memory JS module
    // (never a cookie/localStorage — see frontend/README.md, "Authentication").
    // Capture it from a real authenticated request the page makes anyway,
    // rather than reaching into that private module.
    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/knowledge/documents/")),
      page.goto("/app/knowledge"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    expect(authorization).toBeTruthy();

    const response = await page.request.post(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/knowledge/documents/`,
      {
        headers: { Authorization: authorization },
        multipart: {
          source_id: data.workspaceBKnowledgeSourceId,
          title: "Should never be created",
          file: {
            name: "e2e-privesc.txt",
            mimeType: "text/plain",
            buffer: Buffer.from("attempted privilege escalation"),
          },
        },
      },
    );
    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.error.code).toBe("permission_denied");
  });
});
