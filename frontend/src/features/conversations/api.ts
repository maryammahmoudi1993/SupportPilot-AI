/**
 * Typed API boundary for the conversations domain.
 *
 * Every call goes through `apiClient` + `unwrap(withRequestTimeout(...))` —
 * the same pattern as `features/customers/api.ts` — no raw `fetch`.
 *
 * Schema gaps (Category A — typing deficiencies, not missing capabilities):
 *
 * 1. Conversation list filters: the generated
 *    `api_v1_workspaces_conversations_list` operation only types
 *    `ordering`, `page`, `page_size`, `search` as query parameters (global
 *    filter-backend inference — same shape as the customers list gap from
 *    Chunk 1). The REAL, backend-tested filters
 *    (conversations/views.py `ConversationListCreateView.get_queryset`,
 *    conversations/selectors.py `conversation_list_for_workspace`) are
 *    `customer`, `status`, `channel`, `assigned_to`, and `unassigned` — none
 *    of which drf-spectacular can see, because the view reads them directly
 *    from `request.query_params` rather than a filter backend attribute.
 *    `ConversationListQuery` below narrows this explicitly. `customer` was
 *    already real in Chunk 2 but unused; Chunk 3 wires it up for real
 *    cross-domain contextual links (Customer detail → Inbox).
 * 2. `ordering` and `search` are dead parameters on BOTH the conversation
 *    list and message list endpoints: they appear in the generated schema
 *    only because `OrderingFilter`/`SearchFilter` are in the project's
 *    global `DEFAULT_FILTER_BACKENDS`, but neither view sets
 *    `ordering_fields`/`search_fields`, and neither selector accepts a
 *    `search` argument at all — the backend silently ignores both. Never
 *    sent (same reasoning as the customers `ordering` gap from Chunk 1).
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  Conversation,
  ConversationListParams,
  MessageListParams,
  PaginatedConversationList,
  PaginatedMessageList,
} from "@/features/conversations/types";
import type { paths } from "@/types/api";

type GeneratedConversationListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/conversations/"]["get"]["parameters"]["query"]
>;

/** See the module doc comment: `status`/`channel`/`unassigned` are real but absent from the generated schema. */
type ConversationListQuery = Omit<GeneratedConversationListQuery, "ordering" | "search"> & {
  status?: string;
  channel?: string;
  unassigned?: boolean;
  customer?: string;
};

function toConversationListQuery(params: ConversationListParams): ConversationListQuery {
  const query: ConversationListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  if (params.channel !== "all") {
    query.channel = params.channel;
  }
  if (params.assignment === "unassigned") {
    query.unassigned = true;
  }
  if (params.customerId) {
    query.customer = params.customerId;
  }
  return query;
}

export function fetchConversationList(
  workspaceId: string,
  params: ConversationListParams,
  signal?: AbortSignal,
): Promise<PaginatedConversationList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/conversations/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toConversationListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchConversationDetail(
  workspaceId: string,
  conversationId: string,
  signal?: AbortSignal,
): Promise<Conversation> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/", {
          params: { path: { workspace_id: workspaceId, conversation_id: conversationId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

type GeneratedMessageListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/"]["get"]["parameters"]["query"]
>;
type MessageListQuery = Omit<GeneratedMessageListQuery, "ordering" | "search">;

function toMessageListQuery(params: MessageListParams): MessageListQuery {
  const query: MessageListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  return query;
}

/**
 * Ordering: the backend orders messages by `(created_at, sequence)`
 * ascending — oldest first (conversations/selectors.py
 * `message_list_for_conversation`). `sequence` is a strictly-increasing,
 * DB-assigned insertion sequence introduced specifically to break
 * same-`created_at` ties deterministically (Phase 16; see
 * `Message.sequence`'s backend docstring) — the API's page order is already
 * the authoritative chronological order, and the frontend must render
 * `results` exactly as received, never re-sort by timestamp alone (a
 * client-side re-sort by `created_at` would silently undo that tie-break
 * for messages sharing the same instant).
 */
export function fetchMessageList(
  workspaceId: string,
  conversationId: string,
  params: MessageListParams,
  signal?: AbortSignal,
): Promise<PaginatedMessageList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/",
          {
            params: {
              path: { workspace_id: workspaceId, conversation_id: conversationId },
              query: toMessageListQuery(params),
            },
            signal: requestSignal,
          },
        ),
      undefined,
      signal,
    ),
  );
}
