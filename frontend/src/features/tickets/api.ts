/**
 * Typed API boundary for the tickets domain.
 *
 * Every call goes through `apiClient` + `unwrap(withRequestTimeout(...))` —
 * the same pattern as `features/customers/api.ts` and
 * `features/conversations/api.ts` — no raw `fetch`.
 *
 * Schema gaps (Category A — typing deficiencies, not missing capabilities):
 *
 * 1. Ticket list filters: the generated `api_v1_workspaces_tickets_list`
 *    operation only types `ordering`, `page`, `page_size`, `search` as query
 *    parameters (the same global filter-backend inference gap already
 *    documented for customers and conversations). The REAL, backend-tested
 *    filters (tickets/views.py `TicketListCreateView.get_queryset`,
 *    tickets/selectors.py `ticket_list_for_workspace`) are `status`,
 *    `priority`, `customer`, `assigned_to`, `unassigned`, and `conversation`
 *    — none of which drf-spectacular can see, because the view reads them
 *    directly from `request.query_params` rather than a filter backend
 *    attribute. `TicketListQuery` below narrows this explicitly.
 * 2. `ordering` and `search` are dead parameters, exactly as for customers
 *    and conversations: the backend sorts tickets itself (priority, then
 *    most-recently-created — see `ticket_list_for_workspace`'s
 *    `_PRIORITY_ORDER` annotation) and never reads `ordering`; there is no
 *    search field on the endpoint at all. Never sent.
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type { PaginatedTicketList, Ticket, TicketListParams } from "@/features/tickets/types";
import type { paths } from "@/types/api";

type GeneratedTicketListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/tickets/"]["get"]["parameters"]["query"]
>;

/** See the module doc comment: `status`/`priority`/`customer` are real but absent from the generated schema. */
type TicketListQuery = Omit<GeneratedTicketListQuery, "ordering" | "search"> & {
  status?: string;
  priority?: string;
  customer?: string;
};

function toTicketListQuery(params: TicketListParams): TicketListQuery {
  const query: TicketListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  if (params.priority !== "all") {
    query.priority = params.priority;
  }
  if (params.customerId) {
    query.customer = params.customerId;
  }
  return query;
}

export function fetchTicketList(
  workspaceId: string,
  params: TicketListParams,
  signal?: AbortSignal,
): Promise<PaginatedTicketList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/tickets/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toTicketListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchTicketDetail(
  workspaceId: string,
  ticketId: string,
  signal?: AbortSignal,
): Promise<Ticket> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/tickets/{ticket_id}/", {
          params: { path: { workspace_id: workspaceId, ticket_id: ticketId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}
