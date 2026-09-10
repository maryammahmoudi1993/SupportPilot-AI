/**
 * React Query hooks for the integrations domain (Chunk 1 — read-only).
 *
 * No polling: unlike a knowledge document's ingestion status, a connection's
 * `status`/`last_checked_at` only ever change as the result of an explicit
 * operator action (create, rotate, enable/disable, test) — none of which
 * this chunk exposes yet — so there is no asynchronous state here for a
 * detail-page poll to usefully watch (master prompt Part D §16-18).
 */
import { useQuery } from "@tanstack/react-query";

import {
  fetchIntegrationConnectionDetail,
  fetchIntegrationConnectionList,
} from "@/features/integrations/api";
import { integrationKeys } from "@/features/integrations/query-keys";
import type {
  IntegrationConnection,
  IntegrationConnectionListParams,
  PaginatedIntegrationConnectionList,
} from "@/features/integrations/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

export function useIntegrationConnectionListQuery(
  workspaceId: string | null,
  params: IntegrationConnectionListParams,
) {
  return useQuery<PaginatedIntegrationConnectionList, ApiError>({
    queryKey: integrationKeys.connectionList(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) =>
      fetchIntegrationConnectionList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
  });
}

export function useIntegrationConnectionDetailQuery(
  workspaceId: string | null,
  connectionId: string | null,
) {
  return useQuery<IntegrationConnection, ApiError>({
    queryKey: integrationKeys.connectionDetail(workspaceId ?? NO_WORKSPACE, connectionId ?? ""),
    queryFn: ({ signal }) =>
      fetchIntegrationConnectionDetail(workspaceId as string, connectionId as string, signal),
    enabled: workspaceId !== null && connectionId !== null,
  });
}
