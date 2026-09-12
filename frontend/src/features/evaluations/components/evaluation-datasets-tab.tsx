"use client";

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useState } from "react";
import type { ChangeEvent } from "react";

import { EvaluationDatasetStatusBadge } from "@/features/evaluations/components/evaluation-badges";
import { EvaluationDatasetForm } from "@/features/evaluations/components/evaluation-dataset-form";
import { useCreateEvaluationDatasetMutation } from "@/features/evaluations/mutations";
import { useEvaluationDatasetListQuery } from "@/features/evaluations/queries";
import type {
  EvaluationDatasetListParams,
  EvaluationDatasetStatusFilter,
} from "@/features/evaluations/types";
import { buildEvaluationDatasetListQueryString } from "@/features/evaluations/url-params";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { Timestamp } from "@/components/support/timestamp";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS: { value: EvaluationDatasetStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
];

/** Datasets tab (Phase 23 Chunk 2) — real dataset list, and a create form
 * gated behind `CanManageEvaluations` (owner/admin/support_manager). */
export function EvaluationDatasetsTab({
  workspaceId,
  params,
  canManage,
}: {
  workspaceId: string;
  params: EvaluationDatasetListParams;
  canManage: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const query = useEvaluationDatasetListQuery(workspaceId, params);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const createMutation = useCreateEvaluationDatasetMutation(workspaceId);

  function pushParams(next: EvaluationDatasetListParams) {
    router.replace(`${pathname}${buildEvaluationDatasetListQueryString(next)}`, { scroll: false });
  }

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, status: event.target.value as EvaluationDatasetStatusFilter, page: 1 });
  }

  const hasFilters = params.status !== "all";

  return (
    <div className="flex flex-col gap-6">
      {canManage && (
        <div className="flex flex-col gap-3">
          <div>
            <Button size="sm" onClick={() => setIsCreateOpen((open) => !open)}>
              {isCreateOpen ? "Cancel" : "New dataset"}
            </Button>
          </div>
          {isCreateOpen && (
            <EvaluationDatasetForm
              mode="create"
              isPending={createMutation.isPending}
              error={createMutation.isError ? createMutation.error.message : null}
              onSubmit={(input) => {
                if (createMutation.isPending) {
                  return;
                }
                createMutation.mutate(input, {
                  onSuccess: () => setIsCreateOpen(false),
                });
              }}
              onCancel={() => setIsCreateOpen(false)}
            />
          )}
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="w-full sm:w-56">
          <Label htmlFor="evaluation-dataset-status-filter">Status</Label>
          <select
            id="evaluation-dataset-status-filter"
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

      {query.isPending && <EvaluationDatasetsListSkeleton />}

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
            {hasFilters ? "No datasets match your filter" : "No evaluation datasets yet"}
          </p>
          <p className="text-text-secondary mt-1 text-sm">
            {hasFilters
              ? "Try a different status."
              : "Evaluation datasets created in this workspace will appear here."}
          </p>
        </div>
      )}

      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <div className="border-border-subtle overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[640px] text-left text-sm">
              <caption className="sr-only">Evaluation datasets in this workspace</caption>
              <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
                <tr>
                  <th scope="col" className="px-4 py-2.5">
                    Name
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody
                className={cn("divide-border-subtle divide-y", query.isFetching && "opacity-60")}
              >
                {query.data.results.map((dataset) => (
                  <tr key={dataset.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        href={`/app/evaluations/datasets/${dataset.id}`}
                        className="text-primary-700 hover:underline focus-visible:underline"
                      >
                        {dataset.name}
                      </Link>
                      {dataset.description && (
                        <div className="text-text-secondary text-xs">{dataset.description}</div>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <EvaluationDatasetStatusBadge status={dataset.status} />
                    </td>
                    <td className="text-text-secondary px-4 py-2.5">
                      <Timestamp value={dataset.created_at} />
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
            summary={`Page ${params.page} · ${query.data.count} dataset${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

function EvaluationDatasetsListSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Loading evaluation datasets">
      {Array.from({ length: 6 }).map((_, index) => (
        <Skeleton key={index} className="h-11 w-full" />
      ))}
      <span className="sr-only">Loading evaluation datasets</span>
    </div>
  );
}
