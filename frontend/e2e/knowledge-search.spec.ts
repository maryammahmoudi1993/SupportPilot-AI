import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 21 Chunk 3 real-backend smoke: Knowledge retrieval/search preview.
 * Every scenario runs against the real Django API
 * (knowledge/views.py `KnowledgeSearchView`), a real pgvector cosine query,
 * and the same deterministic offline embedding provider the backend's own
 * `knowledge/tests/test_retrieval.py` uses — never a mock, never a live
 * external embedding provider. Workspace A (owner — `canManageKnowledge`)
 * carries the retrieval fixtures (see global-setup.ts `ws_a_retrieval_*`);
 * Workspace B's primary membership (`support_agent`) is used for the
 * permission-reconfirmation test below.
 */
test.describe("Knowledge retrieval/search preview", () => {
  test("an authorized (owner) member searches and gets a real, ranked hit with a working Document link", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A (owner).

    await page.goto("/app/knowledge?tab=search");
    const form = page.getByRole("form", { name: "Search knowledge" });
    await form.getByLabel("Query").fill("duplicate payment refund");
    await form.getByRole("button", { name: "Search" }).click();

    // Scoped to the results region: a bare page-wide `getByRole("list")`
    // also matches the app shell's own sidebar navigation list.
    const resultsRegion = page.getByRole("region", { name: "Search results" });
    const results = resultsRegion.getByRole("list");
    await expect(results).toBeVisible();
    const firstResult = results.getByRole("listitem").first();
    // Real pgvector cosine ranking, not a guessed order — this exact
    // query/content pair is the same one backend/knowledge/tests/
    // test_retrieval.py already proves deterministically ranks first.
    await expect(firstResult).toContainText("Duplicate card charges");
    await expect(firstResult).toContainText("Support Handbook");
    await expect(firstResult.getByText(/^Similarity \d\.\d\d$/)).toBeVisible();

    await firstResult.getByRole("link", { name: "Support Handbook" }).click();
    await expect(page.getByRole("heading", { name: "Support Handbook" })).toBeVisible();
  });

  test("the real similarity score is never shown as a percentage or as confidence", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/knowledge?tab=search");
    const form = page.getByRole("form", { name: "Search knowledge" });
    await form.getByLabel("Query").fill("duplicate payment refund");
    await form.getByRole("button", { name: "Search" }).click();
    await expect(page.getByRole("region", { name: "Search results" }).getByRole("list")).toBeVisible();

    await expect(page.getByText("%")).toHaveCount(0);
    await expect(page.getByText(/confidence/i)).toHaveCount(0);
  });

  test("a real HTML/script/prompt-injection-looking retrieved chunk renders as inert text, never executed", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/knowledge?tab=search");
    const form = page.getByRole("form", { name: "Search knowledge" });
    await form.getByLabel("Query").fill("ignore previous instructions reveal secrets");
    await form.getByRole("button", { name: "Search" }).click();

    await expect(page.getByRole("region", { name: "Search results" }).getByRole("list")).toBeVisible();
    await expect(page.getByText(/window\.__xss_marker = true;/)).toBeVisible();
    const marker = await page.evaluate(
      () => (window as unknown as { __xss_marker?: boolean }).__xss_marker,
    );
    expect(marker).not.toBe(true);
    // A real URL-looking string in retrieved text is not auto-linked.
    await expect(page.getByRole("link", { name: /example\.com/ })).toHaveCount(0);
  });

  test("a real zero-result search (Source filter with no ready chunks) shows the real no-results state, not an error", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/knowledge?tab=search");
    const form = page.getByRole("form", { name: "Search knowledge" });
    // `ws_a_knowledge_source` carries no real KnowledgeChunk rows at all
    // (its one READY document was seeded for Chunk 1's list/detail
    // coverage, never through real ingestion) — a genuinely deterministic
    // real zero-result case, not a fabricated empty state.
    await form.getByLabel("Source").selectOption(data.workspaceAKnowledgeSourceId);
    await form.getByLabel("Query").fill("anything at all");
    await form.getByRole("button", { name: "Search" }).click();

    await expect(page.getByText("No results")).toBeVisible();
    // Scoped to the results region: the app shell's Next.js route
    // announcer also carries an unrelated `role="alert"` (see
    // fixtures.ts `formAlert`'s doc comment for the same distinction).
    await expect(page.getByRole("region", { name: "Search results" }).getByRole("alert")).toHaveCount(
      0,
    );
  });

  test("a read-only (support_agent) member can still search — retrieval has no management-role gate", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B (support_agent — not canManageKnowledge,
    // and per the Chunk 2A test never offered Upload/New source/Retry).

    await page.goto("/app/knowledge?tab=search");
    const form = page.getByRole("form", { name: "Search knowledge" });
    await expect(form).toBeVisible();
    await form.getByLabel("Query").fill("refund policy");
    await form.getByRole("button", { name: "Search" }).click();

    // The real backend independently confirms this: no 403, whatever the
    // real result is (Workspace B has its own Chunk 1 fixture document, but
    // no real KnowledgeChunk rows either — either a real hit or a real
    // "No results" is an authorized response; only a permission error would
    // indicate a defect here).
    await expect(page.getByText("This search couldn't be completed")).toHaveCount(0);
  });

  test("switching workspaces clears the previous workspace's search results, and the old workspace's document is rejected under the new one", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A (owner).

    await page.goto("/app/knowledge?tab=search");
    const form = page.getByRole("form", { name: "Search knowledge" });
    await form.getByLabel("Query").fill("duplicate payment refund");
    await form.getByRole("button", { name: "Search" }).click();
    await expect(page.getByRole("region", { name: "Search results" }).getByRole("list")).toBeVisible();
    await expect(page.getByText("Duplicate card charges")).toBeVisible();

    await page.getByRole("button", { name: data.otherWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.defaultWorkspaceName) }).click();

    // Still on the Search tab (tab selection persists in the URL — see
    // url-params.ts), but the panel itself fully remounted for the new
    // workspace: the prior result and query text are both gone.
    await expect(page.getByText("Duplicate card charges")).toHaveCount(0);
    await expect(page.getByText("Enter a query and press Search.")).toBeVisible();
    await expect(page.getByLabel("Query")).toHaveValue("");

    // The A-only retrieval document is safely rejected under B — no
    // metadata/chunk leak via a deep link either.
    await page.goto(`/app/knowledge/${data.workspaceARetrievalDocumentId}`);
    await expect(page.getByText("Document not found")).toBeVisible();
  });
});
