/**
 * React Query hooks for the handoffs domain. No polling: a handoff's state
 * only changes via a manager decision (assign/resolve) this chunk doesn't
 * implement, or another operator's action elsewhere — read-only visibility
 * refreshed on navigation/refetch is honest and sufficient (master prompt
 * doesn't require handoff polling; unlike Approvals, there is no bounded
 * expiry clock racing this view).
 */
import { useQuery } from "@tanstack/react-query";

import {
  fetchHandoffDetail,
  fetchHandoffList,
  fetchHandoffsForConversation,
} from "@/features/handoffs/api";
import { handoffKeys } from "@/features/handoffs/query-keys";
import type {
  HandoffListParams,
  HumanHandoff,
  PaginatedHumanHandoffList,
} from "@/features/handoffs/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

export function useHandoffListQuery(workspaceId: string | null, params: HandoffListParams) {
  return useQuery<PaginatedHumanHandoffList, ApiError>({
    queryKey: handoffKeys.list(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchHandoffList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
  });
}

export function useHandoffDetailQuery(workspaceId: string | null, handoffId: string | null) {
  return useQuery<HumanHandoff, ApiError>({
    queryKey: handoffKeys.detail(workspaceId ?? NO_WORKSPACE, handoffId ?? ""),
    queryFn: ({ signal }) => fetchHandoffDetail(workspaceId as string, handoffId as string, signal),
    enabled: workspaceId !== null && handoffId !== null,
  });
}

/** Real filter (tickets/selectors.py `handoff_list_for_workspace`'s `conversation_id`) — used to embed a conversation's own handoff context. */
export function useHandoffsForConversationQuery(
  workspaceId: string | null,
  conversationId: string | null,
) {
  return useQuery<PaginatedHumanHandoffList, ApiError>({
    queryKey: handoffKeys.forConversation(workspaceId ?? NO_WORKSPACE, conversationId ?? ""),
    queryFn: ({ signal }) =>
      fetchHandoffsForConversation(workspaceId as string, conversationId as string, signal),
    enabled: workspaceId !== null && conversationId !== null,
  });
}
