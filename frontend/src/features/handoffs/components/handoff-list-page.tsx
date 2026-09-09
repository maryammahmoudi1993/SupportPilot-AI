"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import type { ChangeEvent } from "react";

import {
  HandoffStatusBadge,
  handoffReasonLabel,
} from "@/features/handoffs/components/handoff-badges";
import { useHandoffListQuery } from "@/features/handoffs/queries";
import type { HandoffListParams, HandoffStatusFilter } from "@/features/handoffs/types";
import {
  buildHandoffListQueryString,
  parseHandoffListParams,
} from "@/features/handoffs/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: { value: HandoffStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "assigned", label: "Assigned" },
  { value: "resolved", label: "Resolved" },
  { value: "cancelled", label: "Cancelled" },
];

function HandoffsListContent() {
  const workspace = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const params = parseHandoffListParams(searchParams);
  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const query = useHandoffListQuery(workspaceId, params);

  function pushParams(next: HandoffListParams) {
    router.replace(`${pathname}${buildHandoffListQueryString(next)}`, { scroll: false });
  }

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, status: event.target.value as HandoffStatusFilter, page: 1 });
  }

  const hasFilters = params.status !== "all";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Handoffs</h1>
        <p className="text-text-secondary text-sm">
          Real deliberate exits from agent orchestration to a human operator, in this workspace.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-56">
          <Label htmlFor="handoff-status-filter">Status</Label>
          <select
            id="handoff-status-filter"
            value={params.status}
            onChange={handleStatusChange}
            className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {query.isPending && <HandoffsListSkeleton />}

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
            {hasFilters ? "No handoffs match your filter" : "No handoffs yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different status."
              : "Deliberate exits from agent orchestration to a human operator will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[720px] text-left text-sm">
              <caption className="sr-only">Human handoffs in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Reason
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Assigned to
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((handoff) => (
                  <tr key={handoff.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/handoffs/${handoff.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {handoffReasonLabel(handoff.reason_code)}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <HandoffStatusBadge status={handoff.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {handoff.assigned_to?.email ?? "Unassigned"}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={handoff.created_at} />
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
            summary={`Page ${params.page} · ${query.data.count} handoff${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function HandoffsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading handoffs">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading handoffs</span>
    </div>
  );
}

export function HandoffsListPage() {
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
          <Spinner label="Loading handoffs" />
        </div>
      }
    >
      <HandoffsListContent />
    </Suspense>
  );
}
