/**
 * Conversation/message domain types.
 *
 * Re-exported from the generated OpenAPI schema wherever accurate, with two
 * narrow, documented exceptions (Category A schema gaps — see api.ts for
 * the full contract notes):
 *
 * - `Conversation.assigned_to` and `Message.sender` are both nested
 *   `MembershipSummary` read-only fields backing a nullable foreign key
 *   (`assigned_to`/`sender_membership` — see backend/conversations/models.py).
 *   DRF correctly serializes `null` for an unassigned conversation or a
 *   non-human-agent message, but `drf-spectacular` doesn't infer
 *   nullability for a nested read-only serializer tied to a nullable FK the
 *   way it does for a plain scalar field (compare `Customer.email`, which
 *   *is* correctly typed `string | null` elsewhere in this same schema) —
 *   so the generated type omits `| null` here. Both are re-typed below.
 */
import type { components } from "@/types/api";

export type MembershipSummary = components["schemas"]["MembershipSummary"];

export type Conversation = Omit<components["schemas"]["Conversation"], "assigned_to"> & {
  assigned_to: MembershipSummary | null;
};
export type PaginatedConversationList = Omit<
  components["schemas"]["PaginatedConversationList"],
  "results"
> & {
  results: Conversation[];
};

export type Message = Omit<components["schemas"]["Message"], "sender"> & {
  sender: MembershipSummary | null;
};
export type PaginatedMessageList = Omit<components["schemas"]["PaginatedMessageList"], "results"> & {
  results: Message[];
};

export type ConversationStatusValue = components["schemas"]["ConversationStatusEnum"];
export type ConversationChannelValue = components["schemas"]["ConversationChannelEnum"];

/** `"all"` omits the corresponding filter from the request entirely. */
export type ConversationStatusFilter = "all" | ConversationStatusValue;
export type ConversationChannelFilter = "all" | ConversationChannelValue;
/** A real, backend-tested filter (`unassigned=true`) — see conversations/selectors.py. */
export type ConversationAssignmentFilter = "all" | "unassigned";

export interface ConversationListParams {
  page: number;
  status: ConversationStatusFilter;
  channel: ConversationChannelFilter;
  assignment: ConversationAssignmentFilter;
}

export const DEFAULT_CONVERSATION_LIST_PARAMS: ConversationListParams = {
  page: 1,
  status: "all",
  channel: "all",
  assignment: "all",
};

export interface MessageListParams {
  page: number;
}

export const DEFAULT_MESSAGE_LIST_PARAMS: MessageListParams = { page: 1 };
