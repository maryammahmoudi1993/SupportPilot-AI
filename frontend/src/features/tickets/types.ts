/**
 * Ticket domain types.
 *
 * Re-exported from the generated OpenAPI schema wherever accurate, with one
 * narrow, documented exception (Category A schema gap — see api.ts for the
 * full contract notes):
 *
 * - `Ticket.assigned_to` is a nested `MembershipSummary` read-only field
 *   backing a nullable foreign key (`Ticket.assigned_to`, on_delete=SET_NULL
 *   — see backend/tickets/models.py). Same drf-spectacular nullability gap
 *   already documented for `Conversation.assigned_to` and `Message.sender`
 *   in features/conversations/types.ts: a nested read-only serializer tied
 *   to a nullable FK isn't inferred as nullable. Re-typed below.
 */
import type { MembershipSummary } from "@/features/conversations/types";
import type { components } from "@/types/api";

export type Ticket = Omit<components["schemas"]["Ticket"], "assigned_to"> & {
  assigned_to: MembershipSummary | null;
};
export type PaginatedTicketList = Omit<components["schemas"]["PaginatedTicketList"], "results"> & {
  results: Ticket[];
};

export type TicketStatusValue = components["schemas"]["TicketStatusEnum"];
export type TicketPriorityValue = components["schemas"]["PriorityEnum"];

/** `"all"` omits the corresponding filter from the request entirely. */
export type TicketStatusFilter = "all" | TicketStatusValue;
export type TicketPriorityFilter = "all" | TicketPriorityValue;

export interface TicketListParams {
  page: number;
  status: TicketStatusFilter;
  priority: TicketPriorityFilter;
  /**
   * Contextual, URL-driven only — never exposed as a picker in the Tickets
   * list UI itself (master prompt Part K, section 31-32). Set when arriving
   * from a real cross-domain link such as Customer detail's "Related
   * tickets" panel (`/app/tickets?customer=<id>`, a real backend filter —
   * see tickets/selectors.py `ticket_list_for_workspace`).
   */
  customerId: string | null;
}

export const DEFAULT_TICKET_LIST_PARAMS: TicketListParams = {
  page: 1,
  status: "all",
  priority: "all",
  customerId: null,
};
