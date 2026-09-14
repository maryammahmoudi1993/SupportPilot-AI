import { useQuery } from "@tanstack/react-query";

import { fetchWorkspaceDetail, fetchWorkspaceMemberList } from "@/features/workspace-admin/api";
import { workspaceMemberKeys, workspaceSettingsKeys } from "@/features/workspace-admin/query-keys";
import type {
  PaginatedWorkspaceMembershipList,
  Workspace,
  WorkspaceMemberListParams,
} from "@/features/workspace-admin/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

export function useWorkspaceMemberListQuery(
  workspaceId: string | null,
  params: WorkspaceMemberListParams,
) {
  return useQuery<PaginatedWorkspaceMembershipList, ApiError>({
    queryKey: workspaceMemberKeys.list(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchWorkspaceMemberList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
  });
}

/** Phase 24 Chunk 2 — the workspace's own settings (name/slug/etc.), read-only for any active member. */
export function useWorkspaceDetailQuery(workspaceId: string | null) {
  return useQuery<Workspace, ApiError>({
    queryKey: workspaceSettingsKeys.detail(workspaceId ?? NO_WORKSPACE),
    queryFn: ({ signal }) => fetchWorkspaceDetail(workspaceId as string, signal),
    enabled: workspaceId !== null,
  });
}
