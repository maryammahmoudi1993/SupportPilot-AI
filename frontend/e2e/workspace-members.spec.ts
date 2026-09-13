import { expect, test } from "@playwright/test";

import { e2eData, login } from "./fixtures";

/**
 * Phase 24 Chunk 1 real-backend smoke: Workspace Members + Roles
 * (backend/workspaces/views.py `WorkspaceMemberListCreateView`/
 * `WorkspaceMemberDetailView`), never a mock. Workspace A's primary
 * membership is `owner` (real member-management rights, including granting/
 * revoking admin); Workspace B's is `support_agent` (read-only).
 */
test.describe("Workspace Members", () => {
  test("lists real members with textual roles and no role-edit control for a read-only (support_agent) account", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace is B — support_agent.

    await page.goto("/app/settings/members");
    await expect(page.getByRole("heading", { name: "Workspace members" })).toBeVisible();
    await expect(page.getByText(data.workspaceBMembershipOtherEmail)).toBeVisible();
    await expect(page.getByText("Viewer", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("combobox")).toHaveCount(0);
  });

  test("an owner sees real member rows, can grant/revoke admin with confirmation, and never edits their own row", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    await page.getByRole("button", { name: data.defaultWorkspaceName }).click();
    await page.getByRole("menuitem", { name: new RegExp(data.otherWorkspaceName) }).click();
    // Active workspace is now A — owner.

    await page.goto("/app/settings/members");
    await expect(page.getByRole("heading", { name: "Workspace members" })).toBeVisible();
    await expect(page.getByText(data.workspaceAMembershipAdminEmail)).toBeVisible();
    await expect(page.getByText(data.workspaceAMembershipViewerEmail)).toBeVisible();

    // The owner's own row: no edit control, labeled (You).
    await expect(page.getByText("(You)")).toBeVisible();

    const viewerRow = page.getByRole("row", { name: new RegExp(data.workspaceAMembershipViewerEmail) });
    const select = viewerRow.getByRole("combobox");
    await expect(select).toBeVisible();
    await select.selectOption("admin");

    await expect(page.getByRole("heading", { name: "Grant admin access?" })).toBeVisible();
    await page.getByRole("button", { name: "Grant admin" }).click();
    await expect(page.getByRole("heading", { name: "Grant admin access?" })).toHaveCount(0);
    await expect(select).toHaveValue("admin");

    // Revert, so this test never leaves cross-test state behind.
    await select.selectOption("viewer");
    await expect(page.getByRole("heading", { name: "Remove admin access?" })).toBeVisible();
    await page.getByRole("button", { name: "Remove admin" }).click();
    await expect(select).toHaveValue("viewer");
  });

  test("an admin cannot manage another admin — no control renders for that row", async ({ page }) => {
    const data = e2eData();
    // Logged in as e2e-ws-a-admin (admin), whose only membership is
    // Workspace A — the real, authoritative rule this proves is
    // backend/workspaces/permissions.py can_manage_target_role: an admin
    // actor may never manage another admin's role.
    await login(page, data.workspaceAMembershipAdminEmail, data.primaryPassword);

    await page.goto("/app/settings/members");
    await expect(page.getByRole("heading", { name: "Workspace members" })).toBeVisible();
    const otherAdminRow = page.getByRole("row", {
      name: new RegExp(data.workspaceAMembershipAdmin2Email),
    });
    await expect(otherAdminRow).toBeVisible();
    await expect(otherAdminRow.getByRole("combobox")).toHaveCount(0);

    // A lower-role member (viewer) IS manageable by this admin actor.
    const viewerRow = page.getByRole("row", { name: new RegExp(data.workspaceAMembershipViewerEmail) });
    await expect(viewerRow.getByRole("combobox")).toBeVisible();
  });

  test("never renders a manage control for the real support_agent role, and the backend independently denies a direct mutation", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace B — support_agent, not in MEMBER_MANAGEMENT_ROLES.

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/members/")),
      page.goto("/app/settings/members"),
    ]);
    await expect(page.getByRole("combobox")).toHaveCount(0);

    const authorization = listRequest.headers()["authorization"];
    expect(authorization).toBeTruthy();
    const response = await page.request.patch(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/members/${data.workspaceBMembershipOtherId}/`,
      { headers: { Authorization: authorization }, data: { role: "admin" } },
    );
    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.error.code).toBe("permission_denied");
  });

  test("a foreign-workspace membership id is rejected as not_found, never leaked", async ({ page }) => {
    const data = e2eData();
    await login(page, data.primaryEmail, data.primaryPassword);
    // Default active workspace B; workspaceAMembershipAdminId belongs to workspace A.

    const [listRequest] = await Promise.all([
      page.waitForRequest((req) => req.url().includes("/members/")),
      page.goto("/app/settings/members"),
    ]);
    const authorization = listRequest.headers()["authorization"];
    const response = await page.request.get(
      `http://localhost:8000/api/v1/workspaces/${data.workspaceBId}/members/${data.workspaceAMembershipAdminId}/`,
      { headers: { Authorization: authorization } },
    );
    expect(response.status()).toBe(404);
  });

  test("a user with zero workspaces sees the real no-workspace state on /app/settings/members, never privileged member data", async ({
    page,
  }) => {
    const data = e2eData();
    await login(page, data.zeroEmail, data.zeroPassword);
    await page.goto("/app/settings/members");
    await expect(page.getByText("No workspace is available for this account")).toBeVisible();
    const html = await page.content();
    expect(html).not.toContain(data.workspaceAMembershipAdminEmail);
    expect(html).not.toContain(data.workspaceBMembershipOtherEmail);
  });
});
