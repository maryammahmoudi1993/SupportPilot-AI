import { useQuery } from "@tanstack/react-query";

import { fetchWorkspaceMemberList } from "@/features/workspace-admin/api";
import { workspaceMemberKeys } from "@/features/workspace-admin/query-keys";
import type {
  PaginatedWorkspaceMembershipList,
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
