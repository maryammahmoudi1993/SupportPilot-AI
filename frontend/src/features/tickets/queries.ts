/**
 * React Query hooks for the tickets domain. Same conventions as
 * features/customers/queries.ts and features/conversations/queries.ts:
 * workspace-scoped keys, and `placeholderData` reused only when the
 * previous successful query was for the SAME workspace (never across a
 * workspace switch).
 */
import { useQuery } from "@tanstack/react-query";

import { fetchTicketDetail, fetchTicketList } from "@/features/tickets/api";
import { ticketKeys } from "@/features/tickets/query-keys";
import type { PaginatedTicketList, Ticket, TicketListParams } from "@/features/tickets/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

function isSameWorkspaceQuery(queryKey: readonly unknown[], workspaceId: string): boolean {
  return queryKey[1] === workspaceId;
}

export function useTicketListQuery(workspaceId: string | null, params: TicketListParams) {
  return useQuery<PaginatedTicketList, ApiError>({
    queryKey: ticketKeys.list(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchTicketList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
    placeholderData: (previousData, previousQuery) => {
      if (workspaceId === null || !previousQuery) {
        return undefined;
      }
      return isSameWorkspaceQuery(previousQuery.queryKey, workspaceId) ? previousData : undefined;
    },
  });
}

export function useTicketDetailQuery(workspaceId: string | null, ticketId: string | null) {
  return useQuery<Ticket, ApiError>({
    queryKey: ticketKeys.detail(workspaceId ?? NO_WORKSPACE, ticketId ?? ""),
    queryFn: ({ signal }) => fetchTicketDetail(workspaceId as string, ticketId as string, signal),
    enabled: workspaceId !== null && ticketId !== null,
  });
}
