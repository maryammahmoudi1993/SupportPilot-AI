/**
 * React Query hooks for the conversations domain. Same conventions as
 * features/customers/queries.ts: workspace-scoped keys, and
 * `placeholderData` reused only when the previous successful query was for
 * the SAME workspace (never across a workspace switch — see query-keys.ts
 * and Chunk 1's README note on the cross-tenant-flash pitfall).
 */
import { useQuery } from "@tanstack/react-query";

import {
  fetchConversationDetail,
  fetchConversationList,
  fetchMessageList,
} from "@/features/conversations/api";
import { conversationKeys } from "@/features/conversations/query-keys";
import type {
  Conversation,
  ConversationListParams,
  MessageListParams,
  PaginatedConversationList,
  PaginatedMessageList,
} from "@/features/conversations/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

function isSameWorkspaceQuery(queryKey: readonly unknown[], workspaceId: string): boolean {
  return queryKey[1] === workspaceId;
}

export function useConversationListQuery(
  workspaceId: string | null,
  params: ConversationListParams,
) {
  return useQuery<PaginatedConversationList, ApiError>({
    queryKey: conversationKeys.list(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchConversationList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
    placeholderData: (previousData, previousQuery) => {
      if (workspaceId === null || !previousQuery) {
        return undefined;
      }
      return isSameWorkspaceQuery(previousQuery.queryKey, workspaceId) ? previousData : undefined;
    },
  });
}

export function useConversationDetailQuery(
  workspaceId: string | null,
  conversationId: string | null,
) {
  return useQuery<Conversation, ApiError>({
    queryKey: conversationKeys.detail(workspaceId ?? NO_WORKSPACE, conversationId ?? ""),
    queryFn: ({ signal }) =>
      fetchConversationDetail(workspaceId as string, conversationId as string, signal),
    enabled: workspaceId !== null && conversationId !== null,
  });
}

/**
 * Independent of `useConversationDetailQuery` — both fire in parallel off
 * the same `workspaceId`/`conversationId` inputs rather than one waiting on
 * the other, since neither's request actually depends on the other's
 * response (see frontend/README.md, "Query waterfalls").
 */
export function useMessageListQuery(
  workspaceId: string | null,
  conversationId: string | null,
  params: MessageListParams,
) {
  return useQuery<PaginatedMessageList, ApiError>({
    queryKey: conversationKeys.messageList(workspaceId ?? NO_WORKSPACE, conversationId ?? "", params),
    queryFn: ({ signal }) =>
      fetchMessageList(workspaceId as string, conversationId as string, params, signal),
    enabled: workspaceId !== null && conversationId !== null,
    placeholderData: (previousData, previousQuery) => {
      if (workspaceId === null || !previousQuery) {
        return undefined;
      }
      return isSameWorkspaceQuery(previousQuery.queryKey, workspaceId) ? previousData : undefined;
    },
  });
}
