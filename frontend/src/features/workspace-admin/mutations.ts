/**
 * Mutation hooks for the workspace-admin domain (Phase 24 Chunk 1).
 *
 * `retry: 0` (same policy as every other sensitive write — see
 * features/integrations/mutations.ts's doc comment): an automatic client
 * retry could double-submit a role change against an idempotent-looking but
 * audited endpoint. Query invalidation is scoped to exactly this
 * workspace's member lists (never the whole app cache).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateWorkspaceMemberRole } from "@/features/workspace-admin/api";
import { workspaceMemberKeys } from "@/features/workspace-admin/query-keys";
import type { WorkspaceMembership, WorkspaceRoleValue } from "@/features/workspace-admin/types";
import type { ApiError } from "@/lib/api/errors";

export interface UpdateMemberRoleInput {
  membershipId: string;
  role: Exclude<WorkspaceRoleValue, "owner">;
}

export function useUpdateWorkspaceMemberRoleMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<WorkspaceMembership, ApiError, UpdateMemberRoleInput>({
    retry: 0,
    mutationFn: ({ membershipId, role }) =>
      updateWorkspaceMemberRole(workspaceId, membershipId, role),
    onSuccess: () => {
      // The server is authoritative for the resulting role; refetch the
      // list(s) rather than hand-patch cached rows across every possible
      // page/param combination.
      void queryClient.invalidateQueries({ queryKey: workspaceMemberKeys.lists(workspaceId) });
    },
  });
}
