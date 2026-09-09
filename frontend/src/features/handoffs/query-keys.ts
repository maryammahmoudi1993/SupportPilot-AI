/**
 * Typed, workspace-scoped query key factory for the handoffs domain — same
 * policy as every other domain (see features/agent-runs/query-keys.ts).
 */
import type { HandoffListParams } from "@/features/handoffs/types";

export const handoffKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "handoffs"] as const,
  lists: (workspaceId: string) => [...handoffKeys.all(workspaceId), "list"] as const,
  list: (workspaceId: string, params: HandoffListParams) =>
    [...handoffKeys.lists(workspaceId), params] as const,
  /** Filtered by a real conversation ID (tickets/selectors.py `handoff_list_for_workspace`'s
   * `conversation_id` filter) — used to embed a conversation's own handoff context. */
  forConversation: (workspaceId: string, conversationId: string) =>
    [...handoffKeys.lists(workspaceId), "conversation", conversationId] as const,
  details: (workspaceId: string) => [...handoffKeys.all(workspaceId), "detail"] as const,
  detail: (workspaceId: string, handoffId: string) =>
    [...handoffKeys.details(workspaceId), handoffId] as const,
};
