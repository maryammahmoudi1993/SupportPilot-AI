"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import type { ChangeEvent } from "react";

import { AgentRunStatusBadge } from "@/features/agent-runs/components/agent-run-badges";
import { useAgentRunListQuery } from "@/features/agent-runs/queries";
import type { AgentRunListParams, AgentRunStatusFilter } from "@/features/agent-runs/types";
import {
  buildAgentRunListQueryString,
  parseAgentRunListParams,
} from "@/features/agent-runs/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: { value: AgentRunStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "waiting_for_approval", label: "Waiting for approval" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "budget_exceeded", label: "Budget exceeded" },
  { value: "handed_off", label: "Handed off" },
];

function AgentRunsListContent() {
  const workspace = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const params = parseAgentRunListParams(searchParams);
  const workspaceId = workspace.activeWorkspace?.id ?? null;
  const query = useAgentRunListQuery(workspaceId, params);

  function pushParams(next: AgentRunListParams) {
    router.replace(`${pathname}${buildAgentRunListQueryString(next)}`, { scroll: false });
  }

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, status: event.target.value as AgentRunStatusFilter, page: 1 });
  }

  const hasFilters = params.status !== "all";

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-text-primary text-xl font-semibold">Agent Runs</h1>
        <p className="text-text-secondary text-sm">
          Real AI agent executions in this workspace — status, lifecycle, and outcome.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-56">
          <Label htmlFor="agent-run-status-filter">Status</Label>
          <select
            id="agent-run-status-filter"
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

      {query.isPending && <AgentRunsListSkeleton />}

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
            {hasFilters ? "No agent runs match your filter" : "No agent runs yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different status."
              : "Runs this workspace's agents execute will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[760px] text-left text-sm">
              <caption className="sr-only">Agent runs in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Run
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Trigger
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Steps
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Tool calls
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((run) => (
                  <tr key={run.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/agent-runs/${run.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        Run #{run.id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="text-text-secondary px-4 py-2.5 capitalize">{run.trigger}</td>
                    <td className="px-4 py-2.5">
                      <AgentRunStatusBadge status={run.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">{run.step_count}</td>
                    <td className="text-text-secondary px-4 py-2.5">{run.tool_call_count}</td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={run.created_at} />
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
            summary={`Page ${params.page} · ${query.data.count} run${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function AgentRunsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading agent runs">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading agent runs</span>
    </div>
  );
}

export function AgentRunsListPage() {
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
          <Spinner label="Loading agent runs" />
        </div>
      }
    >
      <AgentRunsListContent />
    </Suspense>
  );
}
