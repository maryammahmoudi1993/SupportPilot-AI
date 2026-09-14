/**
 * Mutation hooks for the workspace-admin domain.
 *
 * `retry: 0` on every mutation here (same policy as every other sensitive
 * write — see features/integrations/mutations.ts's doc comment): an
 * automatic client retry could double-submit a role change, double-add a
 * member, or double-remove one. Query invalidation is scoped to exactly
 * this workspace's own keys (never the whole app cache).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  addWorkspaceMember,
  removeWorkspaceMember,
  updateWorkspace,
  updateWorkspaceMemberRole,
} from "@/features/workspace-admin/api";
import { workspaceMemberKeys, workspaceSettingsKeys } from "@/features/workspace-admin/query-keys";
import type {
  AddWorkspaceMemberInput,
  UpdateWorkspaceInput,
  Workspace,
  WorkspaceMembership,
  WorkspaceRoleValue,
} from "@/features/workspace-admin/types";
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

// ---------------------------------------------------------------------------
// Phase 24 Chunk 2 — Workspace settings + add/remove member
// ---------------------------------------------------------------------------

export function useUpdateWorkspaceMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<Workspace, ApiError, UpdateWorkspaceInput>({
    retry: 0,
    mutationFn: (input) => updateWorkspace(workspaceId, input),
    onSuccess: (workspace) => {
      queryClient.setQueryData(workspaceSettingsKeys.detail(workspaceId), workspace);
    },
  });
}

/**
 * No client-supplied idempotency key exists for add-member (backend/
 * workspaces/serializers.py `MemberAddSerializer` — `email`, `role` only),
 * so an ambiguous add (network/timeout failure — the request may or may not
 * have reached the server) must never be blindly resubmitted; same pattern
 * as `isAmbiguousIntegrationMutationError` in features/integrations/
 * mutations.ts. A genuine duplicate submit is independently rejected by the
 * backend anyway (`ConflictError` — "This user is already a member of the
 * workspace.").
 */
export function isAmbiguousAddMemberError(error: ApiError): boolean {
  return error.code === "network_error" || error.code === "timeout";
}

export function useAddWorkspaceMemberMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<WorkspaceMembership, ApiError, AddWorkspaceMemberInput>({
    retry: 0,
    mutationFn: (input) => addWorkspaceMember(workspaceId, input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: workspaceMemberKeys.lists(workspaceId) });
    },
  });
}

export function useRemoveWorkspaceMemberMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    retry: 0,
    mutationFn: (membershipId) => removeWorkspaceMember(workspaceId, membershipId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: workspaceMemberKeys.lists(workspaceId) });
    },
  });
}
