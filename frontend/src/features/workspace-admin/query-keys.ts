/**
 * Typed, workspace-scoped query key factory for the workspace-admin domain —
 * same policy as every other domain (see features/integrations/query-keys.ts).
 * Every branch includes the workspace ID so a workspace switch can never
 * read another workspace's members out of the cache, and so a late-arriving
 * response for a since-abandoned workspace can only ever resolve into that
 * workspace's own, no-longer-rendered key.
 */
import type { WorkspaceMemberListParams } from "@/features/workspace-admin/types";

export const workspaceMemberKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "settings", "members"] as const,

  lists: (workspaceId: string) => [...workspaceMemberKeys.all(workspaceId), "list"] as const,
  list: (workspaceId: string, params: WorkspaceMemberListParams) =>
    [...workspaceMemberKeys.lists(workspaceId), params] as const,
};

/** Phase 24 Chunk 2 — the workspace-settings (name/slug/etc.) detail query key. */
export const workspaceSettingsKeys = {
  detail: (workspaceId: string) => ["workspaces", workspaceId, "settings", "workspace"] as const,
};
