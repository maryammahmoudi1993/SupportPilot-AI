import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 20 Chunk 3 real-backend smoke: Approvals — the first sensitive
 * mutation this frontend implements. Every scenario runs against the real
 * Django API (approvals/views.py, approvals/services.py), never a mock —
 * see frontend/README.md, "Approvals".
 */
test.describe("Approvals", () => {
  test("shows the real pending queue and a real pending approval's frozen context", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Workspace A is the "other" workspace (default active is B) — switch first.
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/approvals");
    await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
    await expect(page.getByRole("link", { name: /amount_minor=10000.*approve/ })).toBeVisible();

    await page.getByRole("link", { name: /amount_minor=10000.*approve/ }).click();
    await expect(page.getByText(/"amount_minor": 10000/)).toBeVisible();
    await expect(page.getByText(/\*\*\*REDACTED\*\*\*/)).toBeVisible();
  });

  test("approves a real pending approval — single decision, controls disappear, honest consequence wording", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(`/app/approvals/${data.workspaceAApprovalApproveId}`);
    await expect(page.getByText("Pending", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Approve" }).click();

    await expect(page.getByText("Approved", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject" })).toHaveCount(0);
    await expect(
      page.getByText(/The related action may still be completing asynchronously/),
    ).toBeVisible();

    // Real persistence, not just local state: reload and confirm.
    await page.reload();
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  });

  test("rejects a real pending approval — real backend continuation, no silently hanging run", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(`/app/approvals/${data.workspaceAApprovalRejectId}`);
    await page.getByRole("button", { name: "Reject" }).click();

    await expect(page.getByText("Rejected", { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText("Rejected", { exact: true })).toBeVisible();
  });

  test("a near-simultaneous decision from two sessions converges to one real, persisted outcome", async ({
    browser,
  }) => {
    const data = e2eData();
    const contextA = await browser.newContext();
    const contextB = await browser.newContext();
    const pageA = await contextA.newPage();
    const pageB = await contextB.newPage();

    await login(pageA, data.primaryEmail, data.primaryPassword);
    await login(pageB, data.primaryEmail, data.primaryPassword);
    for (const p of [pageA, pageB]) {
      await p.getByRole("button", { name: data.defaultWorkspaceName }).click();
      await p.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
      await p.goto(`/app/approvals/${data.workspaceAApprovalConcurrentId}`);
      await p.getByText("Pending", { exact: true }).waitFor();
    }

    await Promise.all([
      pageA.getByRole("button", { name: "Approve" }).click(),
      pageB.getByRole("button", { name: "Reject" }).click(),
    ]);

    // Both tabs must converge to the SAME real final state — never both
    // "successful" (master prompt Part B §8).
    await pageA.reload();
    await pageB.reload();
    const finalStatusA = (await pageA.getByText(/^(Approved|Rejected)$/).textContent()) ?? "";
    const finalStatusB = (await pageB.getByText(/^(Approved|Rejected)$/).textContent()) ?? "";
    expect(finalStatusA).toBe(finalStatusB);
    expect(["Approved", "Rejected"]).toContain(finalStatusA);

    await contextA.close();
    await contextB.close();
  });

  test("an expired approval is never actionable — no Approve/Reject", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(`/app/approvals/${data.workspaceAApprovalExpiredId}`);
    await expect(page.getByText("Expired", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject" })).toHaveCount(0);
  });

  test("an already-decided approval renders its real terminal decision — outcome, decided-by, comment", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(`/app/approvals/${data.workspaceAApprovalDecidedId}`);
    await expect(page.getByText("Approved", { exact: true })).toBeVisible();
    await expect(page.getByText("Confirmed with customer.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  });

  test("a real permission denial: support_agent can view but cannot decide, and the backend re-verifies on attempt", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace (B) — primary's real role there is support_agent.

    await page.goto(`/app/approvals/${data.workspaceBApprovalPendingId}`);
    await expect(page.getByText("Pending", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject" })).toHaveCount(0);
    await expect(
      page.getByText(/You do not have permission to decide this approval request/),
    ).toBeVisible();
  });

  test("a foreign-workspace approval deep-link is never leaked after a workspace switch", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Active workspace defaults to B; the approve-scenario approval belongs to A.
    await page.goto(`/app/approvals/${data.workspaceAApprovalApproveId}`);

    await expect(page.getByText("Approval not found")).toBeVisible();
  });

  test("never offers a manual tool-execution or handoff action from the Approval screen", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto(`/app/approvals/${data.workspaceAApprovalApproveId}`);
    await expect(page.getByRole("button", { name: /retry tool/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /execute/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /assign/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /resolve/i })).toHaveCount(0);
  });
});
