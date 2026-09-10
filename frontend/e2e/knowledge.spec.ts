import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 21 Chunk 1 real-backend smoke: Knowledge/RAG — read-only this
 * chunk (master prompt Part E §21; see frontend/README.md). Every scenario
 * runs against the real Django API (knowledge/views.py
 * `KnowledgeDocumentListCreateView`/`KnowledgeDocumentDetailView`/
 * `KnowledgeSourceListCreateView`), never a mock.
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

  test("never offers an Upload, Retry, or Delete action — read-only this chunk", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);

    await page.goto("/app/knowledge");
    await expect(page.getByRole("button", { name: /^upload$/i })).toHaveCount(0);

    await page.goto(`/app/knowledge/${data.workspaceBKnowledgeDocumentFailedId}`);
    await expect(page.getByRole("button", { name: /^retry$/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^delete$/i })).toHaveCount(0);
  });
});
