/**
 * Shareable/restorable URL query-string state for the ticket list — same
 * pattern and untrusted-input posture as features/customers/url-params.ts
 * and features/conversations/url-params.ts.
 *
 * `customer` is intentionally accepted here even though the Tickets list UI
 * never renders a customer picker: it is how a real cross-domain link (e.g.
 * Customer detail's "Related tickets" panel, `/app/tickets?customer=<id>`)
 * hands off a filter the backend genuinely supports (master prompt Part K).
 * A URL-provided customer ID is still not authorization — it is validated
 * for shape only; the backend's own workspace scoping is what actually
 * enforces access (an ID for a customer in a different workspace simply
 * yields zero matching tickets, never a leak).
 */
import type {
  TicketListParams,
  TicketPriorityFilter,
  TicketStatusFilter,
} from "@/features/tickets/types";
import { DEFAULT_TICKET_LIST_PARAMS } from "@/features/tickets/types";

const VALID_STATUSES: readonly string[] = ["open", "in_progress", "pending", "resolved", "closed"];
const VALID_PRIORITIES: readonly string[] = ["low", "normal", "high", "urgent"];
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function parsePage(raw: string | null): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return DEFAULT_TICKET_LIST_PARAMS.page;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : DEFAULT_TICKET_LIST_PARAMS.page;
}

function parseStatus(raw: string | null): TicketStatusFilter {
  return raw && VALID_STATUSES.includes(raw) ? (raw as TicketStatusFilter) : "all";
}

function parsePriority(raw: string | null): TicketPriorityFilter {
  return raw && VALID_PRIORITIES.includes(raw) ? (raw as TicketPriorityFilter) : "all";
}

function parseCustomerId(raw: string | null): string | null {
  return raw && UUID_PATTERN.test(raw) ? raw : null;
}

export function parseTicketListParams(searchParams: URLSearchParams): TicketListParams {
  return {
    page: parsePage(searchParams.get("page")),
    status: parseStatus(searchParams.get("status")),
    priority: parsePriority(searchParams.get("priority")),
    customerId: parseCustomerId(searchParams.get("customer")),
  };
}

export function buildTicketListQueryString(params: TicketListParams): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  if (params.status !== "all") {
    search.set("status", params.status);
  }
  if (params.priority !== "all") {
    search.set("priority", params.priority);
  }
  if (params.customerId) {
    search.set("customer", params.customerId);
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}
