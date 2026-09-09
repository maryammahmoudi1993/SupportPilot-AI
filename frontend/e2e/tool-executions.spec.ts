import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 20 Chunk 2 real-backend smoke: Tool Executions + Execution Trace,
 * embedded inside Agent Run detail (see frontend/README.md, "Tool
 * Executions"), against the actual Django API. Full accessibility/
 * responsive acceptance is Chunk 4's job — this spec proves the real
 * contract end to end.
 */
test.describe("Tool Executions (embedded in Agent Run detail)", () => {
  test("shows a real successful tool execution with structured output and real risk/side-effect metadata", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);

    await expect(page.getByRole("heading", { name: "Tool executions" })).toBeVisible();
    // demo.echo's real ToolDefinition metadata (tools/demo_tools.py).
    await expect(page.getByText("Echo", { exact: true })).toBeVisible();
    await expect(page.getByText("Read only").first()).toBeVisible();
    await expect(page.getByText("No side effect").first()).toBeVisible();

    // StructuredPayload defaults open — the result is visible without
    // needing to expand a collapsed disclosure first.
    await expect(page.getByText(/"echoed": "hello"/)).toBeVisible();
  });

  test("shows a real failed tool execution's safe error and multiple real attempts, never a raw traceback", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);

    await expect(page.getByText("Deterministic demo failure.")).toBeVisible();
    await expect(page.getByText("tool_execution_failed")).toBeVisible();
    await expect(page.getByText("Traceback", { exact: false })).toHaveCount(0);
    await expect(page.getByText(/File "/)).toHaveCount(0);
  });

  test("never reveals a value the real backend redaction contract replaced with ***REDACTED***", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);

    await expect(page.getByText(/\*\*\*REDACTED\*\*\*/).first()).toBeVisible();
    // The fake secret value seeded in global-setup.ts must never appear —
    // proving the real backend redaction contract, not a frontend guess.
    await expect(page.getByText("fake-not-a-real-secret")).toHaveCount(0);
  });

  test("shows the real, read-only waiting_for_approval status on the non-terminal run — no Approve/Reject action", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunRunningId}`);

    await expect(page.getByText("Waiting for approval").first()).toBeVisible();
    await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /reject/i })).toHaveCount(0);
  });

  test("never offers a manual tool-execution action (Retry/Run/Execute)", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);

    await expect(page.getByRole("button", { name: /retry tool/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /run tool/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^execute$/i })).toHaveCount(0);
  });

  test("a foreign-workspace run's tool executions are never visible after a workspace switch", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.goto(`/app/agent-runs/${data.workspaceBAgentRunSucceededId}`);
    await expect(page.getByText("Echo", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    await page.goto(`/app/agent-runs/${data.workspaceAAgentRunId}`);

    await expect(page.getByText("No tool executions recorded for this run.")).toBeVisible();
    await expect(page.getByText("Echo", { exact: true })).toHaveCount(0);
  });
});
