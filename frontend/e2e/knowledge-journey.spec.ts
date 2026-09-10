import path from "node:path";

import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 21 Chunk 4 (final Knowledge/RAG acceptance gate, Part B §6): one
 * coherent real-browser journey chaining every proven Phase 21 capability
 * end to end — upload -> persist -> queue -> real Celery processing ->
 * chunk/embed -> ready -> retrieve -> workspace isolation -> logout. Every
 * individual step here is already covered in isolation by knowledge.spec.ts
 * and knowledge-search.spec.ts; this spec's distinct value is proving the
 * pieces genuinely compose — a real upload this test performs itself
 * (not a pre-seeded fixture) is the one later found by a real retrieval
 * search — never a mock, never a live external embedding provider.
 *
 * Phase 22 Chunk 1B: uploads into its own dedicated
 * `workspaceAKnowledgeJourneySourceId` (global-setup.ts), never the shared
 * `workspaceARetrievalSourceId` — that Source also receives
 * keyboard-journey.spec.ts's own real upload of the exact same
 * byte-identical fixture file, which produces a genuine similarity tie
 * under the deterministic hash embedding provider (real backend behavior,
 * not a defect); this journey's own "my upload ranks first" assertion
 * cannot assume anything about a document another, independently-authored
 * spec puts into a Source this one doesn't own. The retrieval step also
 * scopes the real Source filter to this dedicated Source, so the search is
 * provably isolated from every other spec's fixture data regardless of
 * upload order — this is real UI + real API filter + real backend
 * retrieval + real deterministic embedding, none of it weakened.
 */
test.describe("Knowledge: the complete real RAG journey", () => {
  test("upload -> real Celery ingestion -> ready -> retrieve -> workspace isolation -> logout", async ({
    page,
  }) => {
    const data = e2eData();

    // 1-2. login, open Knowledge
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto("/app/knowledge");

    // 3. Source already exists for Workspace A (no need to create one for
    // this journey — Chunk 2's own dedicated test already proves real
    // Source creation in isolation) — switch into Workspace A first.
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto("/app/knowledge");

    // 4. upload a real, valid document into this journey's own dedicated
    // Source (Phase 22 Chunk 1B — see the module doc comment above for why
    // this must not be the shared workspaceARetrievalSourceId).
    await page.getByRole("button", { name: "Upload document" }).click();
    const uploadForm = page.getByRole("form", { name: "Upload a knowledge document" });
    await uploadForm.getByLabel("Source").selectOption(data.workspaceAKnowledgeJourneySourceId);
    await uploadForm.getByLabel("Title").fill("RAG journey document");
    await uploadForm
      .getByLabel("File")
      .setInputFiles(path.join(__dirname, "fixtures-data", "e2e-upload.txt"));
    await uploadForm.getByRole("button", { name: "Upload" }).click();

    // 5-6. real Document detail, real server status observed
    await expect(page.getByRole("heading", { name: "RAG journey document" })).toBeVisible();

    // 7-8. real Celery processing genuinely reaches ready
    await expect(page.getByText("Ready", { exact: true }).first()).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("Settled")).toBeVisible();

    // 9. real chunk_count/processing metadata, not fabricated
    await expect(page.getByText("Extracted characters")).toBeVisible();
    const chunksRow = page.locator("dt", { hasText: "Chunks" }).locator("xpath=..");
    await expect(chunksRow.locator("dd")).not.toHaveText("0");

    // 10-13. Search tab, a real deterministic query matching this exact
    // document's own real content (see e2e/fixtures-data/e2e-upload.txt) —
    // the deterministic offline embedding provider is a hashed-token
    // projection, so distinctive shared words reliably dominate cosine
    // similarity against this workspace's other (topically unrelated)
    // fixture chunks. The real Source filter scopes this search to this
    // journey's own dedicated Source (Phase 22 Chunk 1B) — this document is
    // the only one that can ever exist there, so the result is provably
    // isolated from every other spec's fixture data, independent of run
    // order — never weakened to "some result exists."
    await page.goto("/app/knowledge?tab=search");
    const searchForm = page.getByRole("form", { name: "Search knowledge" });
    await searchForm
      .getByLabel("Source")
      .selectOption(data.workspaceAKnowledgeJourneySourceId);
    await searchForm.getByLabel("Query").fill("harmless synthetic text document ingestion pipeline");
    await searchForm.getByRole("button", { name: "Search" }).click();

    // 14-15. a real, backend-ranked hit; real Similarity semantics
    const resultsRegion = page.getByRole("region", { name: "Search results" });
    await expect(resultsRegion.getByRole("list")).toBeVisible();
    const firstResult = resultsRegion.getByRole("listitem").first();
    await expect(firstResult).toContainText("RAG journey document");
    await expect(firstResult.getByText(/^Similarity \d\.\d\d$/)).toBeVisible();

    // 16-17. follow the real Document link, return to Knowledge
    await firstResult.getByRole("link", { name: "RAG journey document" }).click();
    await expect(page.getByRole("heading", { name: "RAG journey document" })).toBeVisible();
    await page.getByRole("link", { name: "← Back to Knowledge" }).click();
    await page.waitForURL("**/app/knowledge");

    // 18-19. switch workspace, verify real isolation
    await page.getByRole("button", { name: data.otherWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.defaultWorkspaceName) }).click();
    await expect(page.getByRole("link", { name: "RAG journey document" })).toHaveCount(0);

    // 20. logout
    await page.getByRole("button", { name: /Account menu/i }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await page.waitForURL("**/login");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
