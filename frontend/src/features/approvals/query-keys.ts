/**
 * Typed, workspace-scoped query key factory for the approvals domain — same
 * policy as every other domain (see features/agent-runs/query-keys.ts):
 * every key embeds the workspace ID as its second segment, so a workspace
 * switch produces a disjoint cache entry, never a stale one another
 * workspace could render.
 */
import type { ApprovalListParams } from "@/features/approvals/types";

export const approvalKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "approvals"] as const,
  lists: (workspaceId: string) => [...approvalKeys.all(workspaceId), "list"] as const,
  list: (workspaceId: string, params: ApprovalListParams) =>
    [...approvalKeys.lists(workspaceId), params] as const,
  details: (workspaceId: string) => [...approvalKeys.all(workspaceId), "detail"] as const,
  detail: (workspaceId: string, approvalId: string) =>
    [...approvalKeys.details(workspaceId), approvalId] as const,
};
