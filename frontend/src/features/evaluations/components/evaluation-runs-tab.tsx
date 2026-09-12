"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useState } from "react";
import type { ChangeEvent } from "react";

import { EvaluationRunStatusBadge } from "@/features/evaluations/components/evaluation-badges";
import { EvaluationRunCompareResultPanel } from "@/features/evaluations/components/evaluation-run-compare-panel";
import { useCompareEvaluationRunsMutation } from "@/features/evaluations/mutations";
import { useEvaluationRunListQuery } from "@/features/evaluations/queries";
import type {
  EvaluationRun,
  EvaluationRunListParams,
  EvaluationRunStatusFilter,
} from "@/features/evaluations/types";
import { buildEvaluationRunListQueryString } from "@/features/evaluations/url-params";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: { value: EvaluationRunStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "partial", label: "Partial" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

/**
 * Compare selection + trigger (Phase 23 Chunk 3, evaluations/views.py
 * `EvaluationRunCompareView` / services.py `compare_evaluation_runs`): a
 * real, server-computed, per-case comparison of two runs over the same
 * dataset — client-side selection of exactly two runs from THIS page's
 * already-fetched list, never a fabricated client-only diff (the backend
 * itself rejects incompatible runs with 400 `evaluation_runs_not_comparable`,
 * verified in `test_compare_rejects_incompatible_runs`). Selection is kept
 * in local component state, not the URL — it is a transient action, not
 * shareable list state like the status filter is.
 */
function useRunSelection() {
  const [selected, setSelected] = useState<string[]>([]);

  function toggle(runId: string) {
    setSelected((current) => {
      if (current.includes(runId)) {
        return current.filter((id) => id !== runId);
      }
      if (current.length >= 2) {
        // Bounded to exactly two — selecting a third replaces the first
        // selected rather than silently refusing the click.
        return [current[1], runId];
      }
      return [...current, runId];
    });
  }

  function clear() {
    setSelected([]);
  }

  return { selected, toggle, clear };
}

/** Runs tab content (Phase 23 Chunk 1, extracted into a tab in Chunk 2 —
 * see evaluations-list-page.tsx). `canRun` (Chunk 3) gates both the compare
 * checkboxes and the Start Run entry point (the dataset detail page is
 * where a run is actually started — see evaluation-dataset-detail-page.tsx
 * — this tab only links there). */
export function EvaluationRunsTab({
  workspaceId,
  params,
  canRun,
}: {
  workspaceId: string;
  params: EvaluationRunListParams;
  canRun: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const query = useEvaluationRunListQuery(workspaceId, params);
  const selection = useRunSelection();
  const compareMutation = useCompareEvaluationRunsMutation(workspaceId);
  const runsById = new Map<string, EvaluationRun>(
    (query.data?.results ?? []).map((run) => [run.id, run]),
  );

  function pushParams(next: EvaluationRunListParams) {
    router.replace(`${pathname}${buildEvaluationRunListQueryString(next)}`, { scroll: false });
  }

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, status: event.target.value as EvaluationRunStatusFilter, page: 1 });
  }

  const hasFilters = params.status !== "all";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-56">
          <Label htmlFor="evaluation-run-status-filter">Status</Label>
          <select
            id="evaluation-run-status-filter"
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

      {query.isPending && <EvaluationRunsListSkeleton />}

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
            {hasFilters ? "No evaluation runs match your filter" : "No evaluation runs yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different status."
              : "Evaluation runs executed in this workspace will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          {canRun && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={selection.selected.length !== 2 || compareMutation.isPending}
                isLoading={compareMutation.isPending}
                onClick={() => {
                  if (compareMutation.isPending || selection.selected.length !== 2) {
                    return;
                  }
                  const [baselineRunId, candidateRunId] = selection.selected;
                  compareMutation.mutate({
                    baseline_run_id: baselineRunId,
                    candidate_run_id: candidateRunId,
                  });
                }}
              >
                Compare selected ({selection.selected.length}/2)
              </Button>
              {selection.selected.length > 0 && (
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    selection.clear();
                    compareMutation.reset();
                  }}
                  disabled={compareMutation.isPending}
                >
                  Clear selection
                </Button>
              )}
              <p className="text-text-secondary text-xs">
                Select exactly two runs over the same dataset to compare their real, server-computed
                metrics.
              </p>
            </div>
          )}

          {compareMutation.isError && (
            <Alert variant="danger" title="These runs could not be compared">
              {compareMutation.error.message}
            </Alert>
          )}

          {compareMutation.isSuccess && (
            <EvaluationRunCompareResultPanel
              result={compareMutation.data}
              baselineRun={runsById.get(compareMutation.data.baseline_run_id)}
              candidateRun={runsById.get(compareMutation.data.candidate_run_id)}
            />
          )}

          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[760px] text-left text-sm">
              <caption className="sr-only">Evaluation runs in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  {canRun && (
                    <th scope="col" className="px-4 py-2.5">
                      <span className="sr-only">Select for comparison</span>
                    </th>
                  )}
                  <th scope="col" className="px-4 py-2.5">
                    Run
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Cases
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Passed
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Failed
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
                    {canRun && (
                      <td className="px-4 py-2.5">
                        <input
                          type="checkbox"
                          aria-label={`Select run ${run.id.slice(0, 8)} for comparison`}
                          checked={selection.selected.includes(run.id)}
                          onChange={() => selection.toggle(run.id)}
                          className="h-4 w-4"
                        />
                      </td>
                    )}
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/evaluations/${run.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        Run #{run.id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <EvaluationRunStatusBadge status={run.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      {run.completed_cases}/{run.total_cases}
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">{run.passed_cases}</td>
                    <td className="text-text-secondary px-4 py-2.5">{run.failed_cases}</td>
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

export function EvaluationRunsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading evaluation runs">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading evaluation runs</span>
    </div>
  );
}
