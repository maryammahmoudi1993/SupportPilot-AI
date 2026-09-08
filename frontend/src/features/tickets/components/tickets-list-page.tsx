"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import type { ChangeEvent } from "react";

import {
  TicketPriorityBadge,
  TicketStatusBadge,
} from "@/features/tickets/components/ticket-badges";
import { useTicketListQuery } from "@/features/tickets/queries";
import type {
  TicketListParams,
  TicketPriorityFilter,
  TicketStatusFilter,
} from "@/features/tickets/types";
import { buildTicketListQueryString, parseTicketListParams } from "@/features/tickets/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { CustomerRefLink } from "@/components/support/customer-ref-link";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: { value: TicketStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In Progress" },
  { value: "pending", label: "Pending" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

const PRIORITY_OPTIONS: { value: TicketPriorityFilter; label: string }[] = [
  { value: "all", label: "All priorities" },
  { value: "urgent", label: "Urgent" },
  { value: "high", label: "High" },
  { value: "normal", label: "Normal" },
  { value: "low", label: "Low" },
];

function TicketsListContent() {
  const workspace = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const params = parseTicketListParams(searchParams);
  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const query = useTicketListQuery(workspaceId, params);

  function pushParams(next: TicketListParams) {
    router.replace(`${pathname}${buildTicketListQueryString(next)}`, { scroll: false });
  }

  function handleSelectChange(field: "status" | "priority") {
    return (event: ChangeEvent<HTMLSelectElement>) => {
      const value = event.target.value;
      if (field === "status") {
        pushParams({ ...params, status: value as TicketStatusFilter, page: 1 });
      } else {
        pushParams({ ...params, priority: value as TicketPriorityFilter, page: 1 });
      }
    };
  }

  function clearCustomerFilter() {
    pushParams({ ...params, customerId: null, page: 1 });
  }

  const hasFilters =
    params.status !== "all" || params.priority !== "all" || params.customerId !== null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Tickets</h1>
        <p className="text-text-secondary text-sm">
          Structured support work items in this workspace.
        </p>
      </div>

      {params.customerId && (
        <div className="border-border-subtle bg-surface-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border px-4 py-2.5 text-sm">
          <span className="text-text-secondary">
            Showing tickets for <CustomerRefLink customerId={params.customerId} />
          </span>
          <button
            type="button"
            onClick={clearCustomerFilter}
            className="text-primary-700 hover:underline focus-visible:underline"
          >
            Clear filter
          </button>
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-48">
          <Label htmlFor="ticket-status-filter">Status</Label>
          <select
            id="ticket-status-filter"
            value={params.status}
            onChange={handleSelectChange("status")}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="w-full sm:w-48">
          <Label htmlFor="ticket-priority-filter">Priority</Label>
          <select
            id="ticket-priority-filter"
            value={params.priority}
            onChange={handleSelectChange("priority")}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {PRIORITY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {query.isPending && <TicketsListSkeleton />}

      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}

      {query.isSuccess && query.data.results.length === 0 && (
        <div className="border-border-subtle rounded-lg border border-dashed py-16 text-center">
          <p className="text-text-primary text-sm font-medium">
            {hasFilters ? "No tickets match your filters" : "No tickets yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different status, priority, or customer filter."
              : "Support tickets this workspace tracks will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[760px] text-left text-sm">
              <caption className="sr-only">Tickets in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Subject
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Customer
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Priority
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Assigned
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((ticket) => (
                  <tr key={ticket.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/tickets/${ticket.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {ticket.subject || "(no subject)"}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <CustomerRefLink customerId={ticket.customer_id} />
                    </td>
                    <td className="px-4 py-2.5">
                      <TicketPriorityBadge priority={ticket.priority} />
                    </td>
                    <td className="px-4 py-2.5">
                      <TicketStatusBadge status={ticket.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {ticket.assigned_to?.email ?? "Unassigned"}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={ticket.created_at} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            page={params.page}
            hasPrevious={query.data.previous !== null && query.data.previous !== undefined}
            hasNext={query.data.next !== null && query.data.next !== undefined}
            onPrevious={() => pushParams({ ...params, page: Math.max(1, params.page - 1) })}
            onNext={() => pushParams({ ...params, page: params.page + 1 })}
            summary={`Page ${params.page} · ${query.data.count} ticket${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function TicketsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading tickets">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading tickets</span>
    </div>
  );
}

export function TicketsListPage() {
  const workspace = useWorkspace();

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <Suspense
      fallback={
        <div className="flex flex-1 items-center justify-center py-16">
          <Spinner label="Loading tickets" />
        </div>
      }
    >
      <TicketsListContent />
    </Suspense>
  );
}
