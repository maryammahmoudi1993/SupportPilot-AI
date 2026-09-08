/**
 * Typed, workspace-scoped query key factory for the customers domain.
 *
 * Every key embeds the workspace ID as its second segment
 * (`["workspaces", workspaceId, ...]`) — this is what lets a workspace
 * switch produce a *disjoint* cache entry rather than a stale one: Workspace
 * A's `["workspaces", "A", "customers", "list", ...]` and Workspace B's
 * `["workspaces", "B", "customers", "list", ...]` never collide, so B can
 * never render A's cached customers (see frontend/README.md, "Workspace-
 * scoped query keys", and Chunk 1's workspace-isolation tests).
 */
import type { CustomerListParams } from "@/features/customers/types";

export const customerKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "customers"] as const,
  lists: (workspaceId: string) => [...customerKeys.all(workspaceId), "list"] as const,
  list: (workspaceId: string, params: CustomerListParams) =>
    [...customerKeys.lists(workspaceId), params] as const,
  details: (workspaceId: string) => [...customerKeys.all(workspaceId), "detail"] as const,
  detail: (workspaceId: string, customerId: string) =>
    [...customerKeys.details(workspaceId), customerId] as const,
};
