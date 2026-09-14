import { describe, expect, it } from "vitest";

import {
  canManageMemberRow,
  canManageMembers,
  canManageTargetRole,
  canManageWorkspace,
  workspaceAdminErrorMessage,
  workspaceRoleLabel,
} from "@/features/workspace-admin/types";
import { workspaceMemberKeys, workspaceSettingsKeys } from "@/features/workspace-admin/query-keys";

describe("canManageMembers", () => {
  it("is true only for owner/admin", () => {
    expect(canManageMembers("owner")).toBe(true);
    expect(canManageMembers("admin")).toBe(true);
    expect(canManageMembers("support_manager")).toBe(false);
    expect(canManageMembers("support_agent")).toBe(false);
    expect(canManageMembers("viewer")).toBe(false);
    expect(canManageMembers(undefined)).toBe(false);
  });
});

describe("canManageTargetRole (mirrors backend can_manage_target_role)", () => {
  it("nobody may manage an owner target", () => {
    expect(canManageTargetRole("owner", "owner")).toBe(false);
    expect(canManageTargetRole("admin", "owner")).toBe(false);
  });

  it("owner may manage any non-owner target, including admin", () => {
    expect(canManageTargetRole("owner", "admin")).toBe(true);
    expect(canManageTargetRole("owner", "support_manager")).toBe(true);
    expect(canManageTargetRole("owner", "support_agent")).toBe(true);
    expect(canManageTargetRole("owner", "viewer")).toBe(true);
  });

  it("admin may manage only roles strictly below admin — never another admin", () => {
    expect(canManageTargetRole("admin", "admin")).toBe(false);
    expect(canManageTargetRole("admin", "support_manager")).toBe(true);
    expect(canManageTargetRole("admin", "support_agent")).toBe(true);
    expect(canManageTargetRole("admin", "viewer")).toBe(true);
  });

  it("no other role may manage anyone", () => {
    for (const target of ["admin", "support_manager", "support_agent", "viewer"]) {
      expect(canManageTargetRole("support_manager", target)).toBe(false);
      expect(canManageTargetRole("support_agent", target)).toBe(false);
      expect(canManageTargetRole("viewer", target)).toBe(false);
      expect(canManageTargetRole(undefined, target)).toBe(false);
    }
  });

  it("this same rule is what makes self-lockout structurally impossible: an admin's own row always has target_role==='admin'", () => {
    expect(canManageTargetRole("admin", "admin")).toBe(false);
  });
});

describe("workspaceRoleLabel", () => {
  it("maps every known role to its label", () => {
    expect(workspaceRoleLabel("owner")).toBe("Owner");
    expect(workspaceRoleLabel("admin")).toBe("Admin");
    expect(workspaceRoleLabel("support_manager")).toBe("Support Manager");
    expect(workspaceRoleLabel("support_agent")).toBe("Support Agent");
    expect(workspaceRoleLabel("viewer")).toBe("Viewer");
  });

  it("never crashes on an unrecognized role — falls back to the raw value", () => {
    expect(workspaceRoleLabel("future_role")).toBe("future_role");
  });
});

describe("canManageWorkspace (mirrors backend CanManageWorkspace.WORKSPACE_SETTINGS_ROLES)", () => {
  it("is true only for owner/admin", () => {
    expect(canManageWorkspace("owner")).toBe(true);
    expect(canManageWorkspace("admin")).toBe(true);
    expect(canManageWorkspace("support_manager")).toBe(false);
    expect(canManageWorkspace("support_agent")).toBe(false);
    expect(canManageWorkspace("viewer")).toBe(false);
    expect(canManageWorkspace(undefined)).toBe(false);
  });
});

describe("canManageMemberRow (shared row-level gate for role-edit and remove controls)", () => {
  it("defers entirely to canManageTargetRole when not self", () => {
    expect(canManageMemberRow("owner", "admin", false)).toBe(true);
    expect(canManageMemberRow("admin", "admin", false)).toBe(false);
    expect(canManageMemberRow("admin", "viewer", false)).toBe(true);
  });

  it("is always false for the caller's own row, defensively, even though canManageTargetRole already refuses every real self case", () => {
    expect(canManageMemberRow("owner", "owner", true)).toBe(false);
    expect(canManageMemberRow("admin", "admin", true)).toBe(false);
  });
});

describe("workspaceAdminErrorMessage (unwraps the real dict-shaped ValidationError envelope)", () => {
  it("returns the specific detail message when the backend wraps it as a generic validation_error", () => {
    expect(
      workspaceAdminErrorMessage({
        code: "validation_error",
        message: "Invalid request.",
        details: { email: "This account could not be added to the workspace." },
      }),
    ).toBe("This account could not be added to the workspace.");
  });

  it("falls back to the top-level message when there is no details object", () => {
    expect(
      workspaceAdminErrorMessage({
        code: "validation_error",
        message: "Invalid request.",
        details: undefined,
      }),
    ).toBe("Invalid request.");
  });

  it("passes through non-validation_error messages unchanged (e.g. permission_denied, conflict)", () => {
    expect(
      workspaceAdminErrorMessage({
        code: "permission_denied",
        message: "You do not have permission to manage this member.",
        details: undefined,
      }),
    ).toBe("You do not have permission to manage this member.");
    expect(
      workspaceAdminErrorMessage({
        code: "conflict",
        message: "This user is already a member of the workspace.",
        details: undefined,
      }),
    ).toBe("This user is already a member of the workspace.");
  });
});

describe("workspaceSettingsKeys", () => {
  it("includes the workspace ID", () => {
    expect(workspaceSettingsKeys.detail("ws-1")).toEqual([
      "workspaces",
      "ws-1",
      "settings",
      "workspace",
    ]);
  });

  it("produces distinct keys for distinct workspaces", () => {
    expect(workspaceSettingsKeys.detail("ws-1")).not.toEqual(workspaceSettingsKeys.detail("ws-2"));
  });
});

describe("workspaceMemberKeys", () => {
  it("includes the workspace ID on every branch", () => {
    expect(workspaceMemberKeys.all("ws-1")).toEqual(["workspaces", "ws-1", "settings", "members"]);
    expect(workspaceMemberKeys.lists("ws-1")).toEqual([
      "workspaces",
      "ws-1",
      "settings",
      "members",
      "list",
    ]);
    expect(workspaceMemberKeys.list("ws-1", { page: 2 })).toEqual([
      "workspaces",
      "ws-1",
      "settings",
      "members",
      "list",
      { page: 2 },
    ]);
  });

  it("produces distinct keys for distinct workspaces", () => {
    expect(workspaceMemberKeys.list("ws-1", { page: 1 })).not.toEqual(
      workspaceMemberKeys.list("ws-2", { page: 1 }),
    );
  });
});
