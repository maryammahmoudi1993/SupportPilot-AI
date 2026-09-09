"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import type { ChangeEvent } from "react";

import { ApprovalStatusBadge } from "@/features/approvals/components/approval-badges";
import { useApprovalListQuery } from "@/features/approvals/queries";
import type { ApprovalListParams, ApprovalStatusFilter } from "@/features/approvals/types";
import {
  buildApprovalListQueryString,
  parseApprovalListParams,
} from "@/features/approvals/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: { value: ApprovalStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
  { value: "cancelled", label: "Cancelled" },
];

function ApprovalsListContent() {
  const workspace = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const params = parseApprovalListParams(searchParams);
  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const query = useApprovalListQuery(workspaceId, params);

  function pushParams(next: ApprovalListParams) {
    router.replace(`${pathname}${buildApprovalListQueryString(next)}`, { scroll: false });
  }

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, status: event.target.value as ApprovalStatusFilter, page: 1 });
  }

  const hasFilters = params.status !== "pending";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Approvals</h1>
        <p className="text-text-secondary text-sm">
          Real actions this workspace&rsquo;s agents paused for a human decision.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-56">
          <Label htmlFor="approval-status-filter">Status</Label>
          <select
            id="approval-status-filter"
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

      {query.isPending && <ApprovalsListSkeleton />}

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
            {hasFilters ? "No approvals match your filter" : "No pending approvals"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different status."
              : "Actions this workspace&rsquo;s agents pause for a human decision will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[720px] text-left text-sm">
              <caption className="sr-only">Approval requests in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Summary
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Required role
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Requested
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Expires
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((approval) => (
                  <tr key={approval.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/approvals/${approval.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {approval.summary}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <ApprovalStatusBadge status={approval.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5 capitalize">
                      {approval.required_role.replace(/_/g, " ")}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={approval.created_at} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={approval.expires_at} />
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
            summary={`Page ${params.page} · ${query.data.count} approval${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function ApprovalsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading approvals">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading approvals</span>
    </div>
  );
}

export function ApprovalsListPage() {
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
          <Spinner label="Loading approvals" />
        </div>
      }
    >
      <ApprovalsListContent />
    </Suspense>
  );
}
