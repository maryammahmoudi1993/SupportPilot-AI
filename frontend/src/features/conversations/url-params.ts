/**
 * Shareable/restorable URL query-string state for the conversation list —
 * same pattern and untrusted-input posture as
 * features/customers/url-params.ts.
 */
import type {
  ConversationAssignmentFilter,
  ConversationChannelFilter,
  ConversationListParams,
  ConversationStatusFilter,
} from "@/features/conversations/types";
import { DEFAULT_CONVERSATION_LIST_PARAMS } from "@/features/conversations/types";

const VALID_STATUSES: readonly string[] = ["open", "pending", "closed"];
const VALID_CHANNELS: readonly string[] = ["web", "chat", "email", "sms", "api"];
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function parsePage(raw: string | null): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return DEFAULT_CONVERSATION_LIST_PARAMS.page;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : DEFAULT_CONVERSATION_LIST_PARAMS.page;
}

function parseStatus(raw: string | null): ConversationStatusFilter {
  return raw && VALID_STATUSES.includes(raw) ? (raw as ConversationStatusFilter) : "all";
}

function parseChannel(raw: string | null): ConversationChannelFilter {
  return raw && VALID_CHANNELS.includes(raw) ? (raw as ConversationChannelFilter) : "all";
}

function parseAssignment(raw: string | null): ConversationAssignmentFilter {
  return raw === "unassigned" ? "unassigned" : "all";
}

/**
 * Contextual, URL-driven only — see the `customerId` field doc comment in
 * types.ts. Still validated for shape (a well-formed UUID); a URL-provided
 * customer ID is not authorization, it's just a real backend filter value
 * (an ID for a customer in a different workspace yields zero matches, never
 * a leak — see conversations/selectors.py `conversation_list_for_workspace`).
 */
function parseCustomerId(raw: string | null): string | null {
  return raw && UUID_PATTERN.test(raw) ? raw : null;
}

export function parseConversationListParams(searchParams: URLSearchParams): ConversationListParams {
  return {
    page: parsePage(searchParams.get("page")),
    status: parseStatus(searchParams.get("status")),
    channel: parseChannel(searchParams.get("channel")),
    assignment: parseAssignment(searchParams.get("assigned")),
    customerId: parseCustomerId(searchParams.get("customer")),
  };
}

export function buildConversationListQueryString(params: ConversationListParams): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  if (params.status !== "all") {
    search.set("status", params.status);
  }
  if (params.channel !== "all") {
    search.set("channel", params.channel);
  }
  if (params.assignment === "unassigned") {
    search.set("assigned", "unassigned");
  }
  if (params.customerId) {
    search.set("customer", params.customerId);
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}

/** Message-timeline pagination: just `?page=`, scoped independently of the list's own query string. */
export function parseMessagePage(searchParams: URLSearchParams): number {
  return parsePage(searchParams.get("page"));
}
