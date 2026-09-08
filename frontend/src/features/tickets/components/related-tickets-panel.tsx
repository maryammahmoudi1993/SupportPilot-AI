"use client";

import Link from "next/link";

import {
  TicketPriorityBadge,
  TicketStatusBadge,
} from "@/features/tickets/components/ticket-badges";
import { useTicketListQuery } from "@/features/tickets/queries";
import { DEFAULT_TICKET_LIST_PARAMS } from "@/features/tickets/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const PREVIEW_COUNT = 5;

/**
 * A bounded, real "related tickets" preview for Customer detail — a single
 * request using the backend's real `customer` filter (see
 * tickets/selectors.py `ticket_list_for_workspace`), never a per-row fetch.
 * Shows at most the first page's first few results with a link to the full
 * filtered list; this is Customer-detail-as-operational-context-hub
 * (master prompt Part F), not a duplicate of the Tickets list itself.
 */
export function RelatedTicketsPanel({
  workspaceId,
  customerId,
}: {
  workspaceId: string;
  customerId: string;
}) {
  const query = useTicketListQuery(workspaceId, { ...DEFAULT_TICKET_LIST_PARAMS, customerId });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Related tickets</CardTitle>
      </CardHeader>
      <CardContent>
        {query.isPending && (
          <div className="flex flex-col gap-2" role="status" aria-label="Loading related tickets">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <span className="sr-only">Loading related tickets</span>
          </div>
        )}

        {query.isError && <p className="text-danger-700 text-sm">{query.error.message}</p>}

        {query.isSuccess && query.data.count === 0 && (
          <p className="text-text-secondary text-sm">No tickets for this customer yet.</p>
        )}

        {query.isSuccess && query.data.count > 0 && (
          <div className="flex flex-col gap-2">
            <ul className="flex flex-col gap-2">
              {query.data.results.slice(0, PREVIEW_COUNT).map((ticket) => (
                <li key={ticket.id} className="flex flex-wrap items-center gap-2 text-sm">
                  <Link
                    href={`/app/tickets/${ticket.id}`}
                    className="text-primary-700 hover:underline focus-visible:underline"
                  >
                    {ticket.subject || "(no subject)"}
                  </Link>
                  <TicketStatusBadge status={ticket.status} />
                  <TicketPriorityBadge priority={ticket.priority} />
                </li>
              ))}
            </ul>
            <Link
              href={`/app/tickets?customer=${customerId}`}
              className="text-primary-700 text-sm hover:underline focus-visible:underline"
            >
              View all {query.data.count} ticket{query.data.count === 1 ? "" : "s"} for this
              customer →
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
