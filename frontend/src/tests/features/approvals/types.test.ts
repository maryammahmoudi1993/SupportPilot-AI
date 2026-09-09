import { describe, expect, it } from "vitest";

import {
  isActionableApprovalStatus,
  isTerminalApprovalStatus,
  roleSatisfiesRequirement,
} from "@/features/approvals/types";

describe("isTerminalApprovalStatus / isActionableApprovalStatus", () => {
  it("treats approved/rejected/expired/cancelled as terminal, non-actionable", () => {
    for (const status of ["approved", "rejected", "expired", "cancelled"] as const) {
      expect(isTerminalApprovalStatus(status)).toBe(true);
      expect(isActionableApprovalStatus(status)).toBe(false);
    }
  });

  it("treats pending as actionable, non-terminal", () => {
    expect(isTerminalApprovalStatus("pending")).toBe(false);
    expect(isActionableApprovalStatus("pending")).toBe(true);
  });

  it("treats an unrecognized future status as neither terminal nor actionable — safe fallback", () => {
    expect(isTerminalApprovalStatus("mystery_status" as never)).toBe(false);
    expect(isActionableApprovalStatus("mystery_status" as never)).toBe(false);
  });
});

describe("roleSatisfiesRequirement", () => {
  it("mirrors the backend's linear escalation (support_manager < admin < owner)", () => {
    expect(roleSatisfiesRequirement("support_manager", "support_manager")).toBe(true);
    expect(roleSatisfiesRequirement("admin", "support_manager")).toBe(true);
    expect(roleSatisfiesRequirement("owner", "support_manager")).toBe(true);
    expect(roleSatisfiesRequirement("owner", "admin")).toBe(true);
    expect(roleSatisfiesRequirement("admin", "owner")).toBe(false);
    expect(roleSatisfiesRequirement("support_manager", "admin")).toBe(false);
  });

  it("denies a role outside the approval-authority ranking entirely (support_agent, viewer)", () => {
    expect(roleSatisfiesRequirement("support_agent", "support_manager")).toBe(false);
    expect(roleSatisfiesRequirement("viewer", "support_manager")).toBe(false);
  });

  it("denies an unrecognized required_role rather than defaulting to permissive", () => {
    expect(roleSatisfiesRequirement("owner", "mystery_role")).toBe(false);
  });
});
