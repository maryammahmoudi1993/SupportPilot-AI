/**
 * Mutation hooks for the integrations domain (Phase 22 Chunk 3).
 *
 * Every mutation here is `retry: 0` (master prompt Part H §33), matching
 * the pattern already established in features/knowledge/mutations.ts and
 * features/approvals/queries.ts's `useDecideApprovalMutation`: an
 * automatic client retry could double-submit a connection create, rotate
 * credentials a second time, or otherwise duplicate a sensitive write.
 *
 * Query invalidation is scoped to exactly the affected connection/list
 * (master prompt Part I §35) — never the whole app cache.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  createIntegrationConnection,
  rotateIntegrationCredentials,
  setIntegrationConnectionEnabled,
  testIntegrationConnection,
  updateIntegrationConnection,
} from "@/features/integrations/api";
import { integrationKeys } from "@/features/integrations/query-keys";
import type {
  CreateIntegrationConnectionInput,
  IntegrationConnection,
  IntegrationConnectionTestResult,
  RotateIntegrationCredentialsInput,
  UpdateIntegrationConnectionInput,
} from "@/features/integrations/types";
import type { ApiError } from "@/lib/api/errors";

/**
 * True only for a request that never reached the backend at all (master
 * prompt Part H §33) — same distinction as
 * `isAmbiguousUploadError` in features/knowledge/mutations.ts. Creation has
 * no client-supplied idempotency key (verified against
 * `integrations/serializers.py IntegrationConnectionCreateSerializer` —
 * `provider`/`display_name`/`environment`/`credentials`/`configuration`
 * only), so an ambiguous create must never be blindly resubmitted; the
 * caller should refresh the connection list first.
 */
export function isAmbiguousIntegrationMutationError(error: ApiError): boolean {
  return error.code === "network_error" || error.code === "timeout";
}

export function useCreateIntegrationConnectionMutation(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<IntegrationConnection, ApiError, CreateIntegrationConnectionInput>({
    retry: 0,
    mutationFn: (input) => createIntegrationConnection(workspaceId, input),
    onSuccess: (connection) => {
      queryClient.setQueryData(
        integrationKeys.connectionDetail(workspaceId, connection.id),
        connection,
      );
      void queryClient.invalidateQueries({ queryKey: integrationKeys.connectionLists(workspaceId) });
    },
  });
}

export function useUpdateIntegrationConnectionMutation(workspaceId: string, connectionId: string) {
  const queryClient = useQueryClient();
  return useMutation<IntegrationConnection, ApiError, UpdateIntegrationConnectionInput>({
    retry: 0,
    mutationFn: (input) => updateIntegrationConnection(workspaceId, connectionId, input),
    onSuccess: (connection) => {
      queryClient.setQueryData(
        integrationKeys.connectionDetail(workspaceId, connectionId),
        connection,
      );
      void queryClient.invalidateQueries({ queryKey: integrationKeys.connectionLists(workspaceId) });
    },
  });
}

export function useRotateIntegrationCredentialsMutation(
  workspaceId: string,
  connectionId: string,
) {
  const queryClient = useQueryClient();
  return useMutation<IntegrationConnection, ApiError, RotateIntegrationCredentialsInput>({
    retry: 0,
    mutationFn: (input) => rotateIntegrationCredentials(workspaceId, connectionId, input),
    onSuccess: (connection) => {
      queryClient.setQueryData(
        integrationKeys.connectionDetail(workspaceId, connectionId),
        connection,
      );
      void queryClient.invalidateQueries({ queryKey: integrationKeys.connectionLists(workspaceId) });
    },
  });
}

export function useSetIntegrationConnectionEnabledMutation(
  workspaceId: string,
  connectionId: string,
) {
  const queryClient = useQueryClient();
  return useMutation<IntegrationConnection, ApiError, boolean>({
    retry: 0,
    mutationFn: (enabled) => setIntegrationConnectionEnabled(workspaceId, connectionId, enabled),
    onSuccess: (connection) => {
      queryClient.setQueryData(
        integrationKeys.connectionDetail(workspaceId, connectionId),
        connection,
      );
      void queryClient.invalidateQueries({ queryKey: integrationKeys.connectionLists(workspaceId) });
    },
  });
}

export function useTestIntegrationConnectionMutation(workspaceId: string, connectionId: string) {
  const queryClient = useQueryClient();
  return useMutation<IntegrationConnectionTestResult, ApiError, void>({
    retry: 0,
    mutationFn: () => testIntegrationConnection(workspaceId, connectionId),
    onSuccess: () => {
      // The real server-derived `status`/`last_checked_at`/`last_error_code`
      // fields this probe just updated live on the connection itself, not
      // on the returned test-result body — refetch the connection so the
      // page reflects what the backend actually recorded, never a
      // client-guessed status transition (master prompt Part D §13).
      void queryClient.invalidateQueries({
        queryKey: integrationKeys.connectionDetail(workspaceId, connectionId),
      });
    },
  });
}
