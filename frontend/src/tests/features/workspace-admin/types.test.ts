import { describe, expect, it } from "vitest";

import {
  canManageMembers,
  canManageTargetRole,
  workspaceRoleLabel,
} from "@/features/workspace-admin/types";
import { workspaceMemberKeys } from "@/features/workspace-admin/query-keys";

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
