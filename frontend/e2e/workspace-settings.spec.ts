import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 24 Chunk 2 real-backend smoke: Workspace Settings (name rename) and
 * Membership Lifecycle (add-member, remove-member) — backend/workspaces/
 * views.py `WorkspaceDetailView`, `WorkspaceMemberListCreateView.create`,
 * `WorkspaceMemberDetailView.delete`, never a mock. Workspace A's primary
 * membership is `owner` (real workspace-settings and member-management
 * rights); Workspace B's is `support_agent` (read-only for both).
 */
test.describe("Workspace Settings", () => {
  test("an owner renames the workspace, and the server-authoritative name is reflected", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A — owner.

    await page.goto("/app/settings/workspace");
    await expect(page.getByRole("heading", { name: "Workspace settings" })).toBeVisible();
    const nameField = page.getByLabel("Name");
    await expect(nameField).toHaveValue(data.otherWorkspaceName);

    await nameField.fill("E2E Workspace A (Renamed)");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Workspace name updated.")).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Name")).toHaveValue("E2E Workspace A (Renamed)");

    // Revert — this workspace's original name is depended on by other
    // specs' `otherWorkspaceName` fixture data.
    await page.getByLabel("Name").fill(data.otherWorkspaceName);
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Workspace name updated.")).toBeVisible();
  });

  test("a support_agent sees the real workspace name but cannot edit it", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace B — support_agent.

    await page.goto("/app/settings/workspace");
    const nameField = page.getByLabel("Name");
    await expect(nameField).toHaveValue(data.defaultWorkspaceName);
    await expect(nameField).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  });

  test("a direct unauthorized workspace-update API call is denied server-side", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace B — support_agent, not in WORKSPACE_SETTINGS_ROLES.
    const [detailRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes(`/workspaces/${data.workspaceBId}/`)),
      page.goto("/app/settings/workspace"),
    ]);
    const authorization = detailRequest.headers()["authorization"];
    expect(authorization).toBeTruthy();

    const response = await page.request.patch(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/`,
      { headers: { Authorization: authorization }, data: { name: "Should not be allowed" } },
    );
    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.error.code).toBe("permission_denied");
  });
});

test.describe("Workspace Membership Lifecycle", () => {
  test("an owner adds an existing, already-active account by exact email — honestly labeled, never an invitation", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/settings/members");
    await page.getByRole("button", { name: "Add member" }).click();
    await expect(page.getByText(/invite/i)).toHaveCount(0);

    await page.getByLabel("Email").fill(data.workspaceAAddableEmail);
    await page.getByRole("button", { name: "Add member" }).click();

    await expect(page.getByText(data.workspaceAAddableDisplayName)).toBeVisible();
  });

  test("adding a nonexistent account shows the real, generic server error (never confirms non-existence explicitly)", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/settings/members");
    await page.getByRole("button", { name: "Add member" }).click();
    await page.getByLabel("Email").fill("e2e-nonexistent-account@example.com");
    await page.getByRole("button", { name: "Add member" }).click();

    await expect(page.getByText("This account could not be added to the workspace.")).toBeVisible();
  });

  test("an owner removes a real member with confirmation, and the server-authoritative removal is reflected", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();

    await page.goto("/app/settings/members");
    await expect(page.getByText(data.workspaceAMembershipRemovableEmail)).toBeVisible();

    const removableRow = page.getByRole("row", {
      name: new RegExp(data.workspaceAMembershipRemovableEmail),
    });
    await removableRow.getByRole("button", { name: /remove/i }).click();
    await expect(page.getByRole("heading", { name: "Remove this member?" })).toBeVisible();
    await page.getByRole("button", { name: "Remove member" }).click();

    await expect(page.getByText(data.workspaceAMembershipRemovableEmail)).toHaveCount(0);
  });

  test("never renders a Remove control for the real support_agent role, and the backend independently denies a direct removal", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace B — support_agent.

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/members/")),
      page.goto("/app/settings/members"),
    ]);
    await expect(page.getByRole("button", { name: /remove/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add member" })).toHaveCount(0);

    const authorization = listRequest.headers()["authorization"];
    const response = await page.request.delete(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/members/${data.workspaceBMembershipOtherId}/`,
      { headers: { Authorization: authorization } },
    );
    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.error.code).toBe("permission_denied");
  });
});
