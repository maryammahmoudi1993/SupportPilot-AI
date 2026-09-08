/**
 * Typed, workspace-scoped query key factory for the conversations domain —
 * same policy as customers (see features/customers/query-keys.ts): every
 * key embeds the workspace ID as its second segment, so a workspace switch
 * produces a disjoint cache entry, never a stale one Workspace B could
 * render.
 *
 * Message keys nest under a conversation's own detail key
 * (`[...detail(id), "messages", params]`) rather than a separate top-level
 * "messages" branch — a conversation's messages are conceptually part of
 * that conversation's own cache subtree, and this keeps a workspace switch
 * invalidating both in one shot (they share the `["workspaces", wsId,
 * "conversations", "detail", conversationId, ...]` prefix).
 */
import type { ConversationListParams, MessageListParams } from "@/features/conversations/types";

export const conversationKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "conversations"] as const,
  lists: (workspaceId: string) => [...conversationKeys.all(workspaceId), "list"] as const,
  list: (workspaceId: string, params: ConversationListParams) =>
    [...conversationKeys.lists(workspaceId), params] as const,
  details: (workspaceId: string) => [...conversationKeys.all(workspaceId), "detail"] as const,
  detail: (workspaceId: string, conversationId: string) =>
    [...conversationKeys.details(workspaceId), conversationId] as const,
  messages: (workspaceId: string, conversationId: string) =>
    [...conversationKeys.detail(workspaceId, conversationId), "messages"] as const,
  messageList: (workspaceId: string, conversationId: string, params: MessageListParams) =>
    [...conversationKeys.messages(workspaceId, conversationId), params] as const,
};
