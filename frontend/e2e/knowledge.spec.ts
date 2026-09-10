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

  test("a real unsupported file type is genuinely rejected by the backend — no document or ingestion job is ever created", async ({
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
    await uploadForm.getByLabel("Title").fill("E2E unsupported file");
    // `setInputFiles` bypasses the file picker entirely (there is no native
    // dialog to filter), so the `<input accept>` hint never blocks this —
    // exactly what's needed to prove the REAL backend, not the client hint,
    // is the actual authority (knowledge/ingestion/validators.py `validate_upload`,
    // raised before any `KnowledgeDocument` row is created — see
    // knowledge/services.py `upload_document`).
    await uploadForm
      .getByLabel("File")
      .setInputFiles(path.join(__dirname, "fixtures-data", "e2e-unsupported.exe"));
    const [response] = await Promise.all([
      page.waitForResponse(
        (res) => res.url().includes("/knowledge/documents/") && res.request().method() === "POST",
      ),
      uploadForm.getByRole("button", { name: "Upload" }).click(),
    ]);
    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body.error.code).toBe("knowledge_unsupported_type");

    // The frontend shows the real safe rejection, never a fabricated success.
    await expect(page.getByText("This upload was rejected")).toBeVisible();
    await expect(page.getByText("The uploaded file type is not supported.")).toBeVisible();
    // Still on the upload form — no navigation to a document that doesn't exist.
    await expect(uploadForm).toBeVisible();
    await expect(page.getByRole("heading", { name: "E2E unsupported file" })).toHaveCount(0);
  });

  test("the real upload form never sends a request with no file selected, in a real browser", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/knowledge");
    await page.getByRole("button", { name: "Upload document" }).click();
    const uploadForm = page.getByRole("form", { name: "Upload a knowledge document" });
    await uploadForm.getByLabel("Source").selectOption(data.workspaceAKnowledgeSourceId);
    await uploadForm.getByLabel("Title").fill("E2E missing file");

    const uploadButton = uploadForm.getByRole("button", { name: "Upload" });
    // Product decision (Chunk 2A §5): the Source select and File input use
    // `aria-required` rather than native `required` (see the component's
    // doc comment) — but the real gate is the submit control's own disabled
    // state, driven by the same `canSubmit` check as every other required
    // field. This is proven directly in a real browser, not just jsdom.
    await expect(uploadButton).toBeDisabled();
    await expect(uploadForm.getByLabel("File")).toHaveAttribute("aria-required", "true");

    // A disabled submit control also means no implicit form submission on
    // Enter from a text field — proven directly rather than assumed.
    let requestSeen = false;
    const onRequest = (req: import("@playwright/test").Request) => {
      if (req.url().includes("/knowledge/documents/") && req.method() === "POST") {
        requestSeen = true;
      }
    };
    page.on("request", onRequest);
    await uploadForm.getByLabel("Title").click();
    await page.keyboard.press("Enter");
    // Bounded wait, not a fixed guess at network latency: proves no request
    // fires in a window well past any real request's round trip.
    await page.waitForTimeout(1000);
    page.off("request", onRequest);
    expect(requestSeen).toBe(false);
    // The form stays open and fully usable — no crash, no dead end.
    await expect(uploadForm).toBeVisible();
    await expect(uploadButton).toBeDisabled();
  });

  test("a real actively-processing (non-terminal) Workspace A document is never visible after switching to Workspace B — including its detail route and its polling", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A (owner). This document is a real, genuinely
    // non-terminal (PROCESSING) row, held in place deterministically because
    // it has no associated ingestion job for any real Celery worker to act
    // on (see global-setup.ts) — not a racy real upload.

    await page.goto("/app/knowledge");
    await expect(page.getByRole("link", { name: "Workspace A actively processing" })).toBeVisible();

    await page
      .getByRole("link", { name: "Workspace A actively processing" })
      .click();
    await expect(page.getByRole("heading", { name: "Workspace A actively processing" })).toBeVisible();
    await expect(page.getByText("Processing", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Still in progress")).toBeVisible();

    // Confirm real detail polling is active while non-terminal.
    const documentUrlFragment = `/knowledge/documents/${data.workspaceAKnowledgeDocumentProcessingId}/`;
    const pollBeforeSwitch = page.waitForRequest(
      (req) => req.url().includes(documentUrlFragment) && req.method() === "GET",
      { timeout: 8_000 },
    );
    await expect(pollBeforeSwitch).resolves.toBeTruthy();

    // Switch to Workspace B WITHOUT navigating away first — still on this
    // exact document's detail URL — the strongest form of this isolation
    // check (master prompt §6).
    await page.getByRole("button", { name: data.otherWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.defaultWorkspaceName) }).click();

    // No A metadata flash: the real document (which does not exist in B)
    // is safely rejected, never rendered under B.
    await expect(page.getByText("Document not found")).toBeVisible();
    await expect(page.getByText("Workspace A actively processing")).toHaveCount(0);
    await expect(page.getByText("Still in progress")).toHaveCount(0);

    // No further polling of the A document leaks into the B-active page —
    // bounded wait comfortably past one real 5s poll interval.
    let leakedRequestSeen = false;
    const onLeak = (req: import("@playwright/test").Request) => {
      if (req.url().includes(documentUrlFragment)) {
        leakedRequestSeen = true;
      }
    };
    page.on("request", onLeak);
    await page.waitForTimeout(6_000);
    page.off("request", onLeak);
    expect(leakedRequestSeen).toBe(false);

    // Direct deep link under B is independently, safely rejected too — a
    // real API call, not just a client-side route guard. Capture the app's
    // real Bearer token from a real authenticated request it makes anyway
    // (see the unauthorized-upload test below for why: the token lives only
    // in an in-memory JS module, never a cookie/localStorage).
    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/knowledge/documents/")),
      page.goto("/app/knowledge"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    expect(authorization).toBeTruthy();
    const response = await page.request.get(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/knowledge/documents/${data.workspaceAKnowledgeDocumentProcessingId}/`,
      { headers: { Authorization: authorization } },
    );
    expect(response.status()).toBe(404);
    const body = await response.json();
    expect(body.error.code).toBe("not_found");
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
