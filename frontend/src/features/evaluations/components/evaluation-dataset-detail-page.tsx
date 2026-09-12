"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";

import {
  EvaluationCaseStatusBadge,
  EvaluationDatasetStatusBadge,
} from "@/features/evaluations/components/evaluation-badges";
import { EvaluationCaseForm } from "@/features/evaluations/components/evaluation-case-form";
import { EvaluationDatasetForm } from "@/features/evaluations/components/evaluation-dataset-form";
import { StartEvaluationRunForm } from "@/features/evaluations/components/start-evaluation-run-form";
import {
  useCreateEvaluationCaseMutation,
  useStartEvaluationRunMutation,
  useUpdateEvaluationCaseMutation,
  useUpdateEvaluationDatasetMutation,
} from "@/features/evaluations/mutations";
import {
  useEvaluationCaseListQuery,
  useEvaluationDatasetDetailQuery,
} from "@/features/evaluations/queries";
import type {
  EvaluationCase,
  EvaluationCaseListParams,
  EvaluationCaseStatusFilter,
} from "@/features/evaluations/types";
import { canManageEvaluations, canRunEvaluations } from "@/features/evaluations/types";
import {
  buildEvaluationCaseListQueryString,
  parseEvaluationCaseListParams,
} from "@/features/evaluations/url-params";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { Pagination } from "@/components/support/pagination";
import { StructuredPayload } from "@/components/support/structured-payload";
import { Timestamp } from "@/components/support/timestamp";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidDatasetId(datasetId: string): boolean {
  return UUID_PATTERN.test(datasetId);
}

function DatasetNotFound() {
  return (
    <EntityNotFound
      title="Evaluation dataset not found"
      description="This evaluation dataset doesn't exist, or isn't available in your active workspace."
      backHref="/app/evaluations?tab=datasets"
      backLabel="Back to Datasets"
    />
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-text-muted text-xs font-medium uppercase">{label}</dt>
      <dd className="text-text-primary text-sm break-words">{value}</dd>
    </div>
  );
}

const CASE_STATUS_OPTIONS: { value: EvaluationCaseStatusFilter; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "disabled", label: "Disabled" },
];

/**
 * One case row, expandable in place to an edit form (master prompt Part C
 * §14: "a detail drawer/expansion may be enough" — there is no separate case
 * detail route because the list response already carries the complete case
 * shape, EvaluationCaseSerializer's fields; a second GET would add nothing).
 */
function CaseRow({
  evaluationCase,
  canManage,
  workspaceId,
  datasetId,
}: {
  evaluationCase: EvaluationCase;
  canManage: boolean;
  workspaceId: string;
  datasetId: string;
}) {
  const [isEditOpen, setIsEditOpen] = useState(false);
  const updateMutation = useUpdateEvaluationCaseMutation(workspaceId, datasetId, evaluationCase.id);

  return (
    <li className="border-border-subtle border-b py-3 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-text-primary text-sm font-medium">{evaluationCase.name}</span>
          <span className="text-text-secondary font-mono text-xs">{evaluationCase.key}</span>
          <EvaluationCaseStatusBadge status={evaluationCase.status} />
        </div>
        {canManage && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setIsEditOpen((open) => !open)}
          >
            {isEditOpen ? "Cancel" : "Edit"}
          </Button>
        )}
      </div>

      {isEditOpen ? (
        <div className="mt-3">
          <EvaluationCaseForm
            mode="edit"
            initial={evaluationCase}
            isPending={updateMutation.isPending}
            error={updateMutation.isError ? updateMutation.error.message : null}
            onSubmit={(input) => {
              if (updateMutation.isPending) {
                return;
              }
              updateMutation.mutate(input, { onSuccess: () => setIsEditOpen(false) });
            }}
            onCancel={() => setIsEditOpen(false)}
          />
        </div>
      ) : (
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {/* Only the Input message is a real name/value pair, so only it
              gets a `<dl>` — `StructuredPayload` renders a `<details>` (or a
              bare `<span>` for an empty value), and a `<dl>` may only
              directly contain `<dt>`/`<dd>` groups (a real axe
              `definition-list` violation found and fixed in Phase 23
              Chunk 4: see "Known defects" below). */}
          <dl className="sm:col-span-2">
            <dt className="text-text-muted text-xs font-medium uppercase">Input message</dt>
            <dd className="text-text-primary text-sm break-words whitespace-pre-wrap">
              {evaluationCase.input_message}
            </dd>
          </dl>
          <div className="sm:col-span-2">
            <StructuredPayload value={evaluationCase.seeded_context} label="Seeded context" />
          </div>
          <div className="sm:col-span-2">
            <StructuredPayload value={evaluationCase.expectations} label="Expectations" />
          </div>
        </div>
      )}
    </li>
  );
}

function CasesPanel({
  workspaceId,
  datasetId,
  canManage,
}: {
  workspaceId: string;
  datasetId: string;
  canManage: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const params = parseEvaluationCaseListParams(searchParams);
  const query = useEvaluationCaseListQuery(workspaceId, datasetId, params);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const createMutation = useCreateEvaluationCaseMutation(workspaceId, datasetId);

  function pushParams(next: EvaluationCaseListParams) {
    router.replace(`${pathname}${buildEvaluationCaseListQueryString(next)}`, { scroll: false });
  }

  function handleStatusChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, status: event.target.value as EvaluationCaseStatusFilter, page: 1 });
  }

  const hasFilters = params.status !== "all";

  return (
    <div className="flex flex-col gap-4">
      {canManage && (
        <div className="flex flex-col gap-3">
          <div>
            <Button size="sm" onClick={() => setIsCreateOpen((open) => !open)}>
              {isCreateOpen ? "Cancel" : "New case"}
            </Button>
          </div>
          {isCreateOpen && (
            <EvaluationCaseForm
              mode="create"
              isPending={createMutation.isPending}
              error={createMutation.isError ? createMutation.error.message : null}
              onSubmit={(input) => {
                if (createMutation.isPending) {
                  return;
                }
                createMutation.mutate(input, { onSuccess: () => setIsCreateOpen(false) });
              }}
              onCancel={() => setIsCreateOpen(false)}
            />
          )}
        </div>
      )}

      <div className="w-full sm:w-56">
        <Label htmlFor="evaluation-case-status-filter">Status</Label>
        <select
          id="evaluation-case-status-filter"
          value={params.status}
          onChange={handleStatusChange}
          className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
        >
          {CASE_STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {query.isPending && (
        <div role="status" aria-label="Loading cases">
          <Skeleton className="h-24 w-full" />
          <span className="sr-only">Loading cases</span>
        </div>
      )}
      {query.isError && (
        <ListError
          message={query.error.message}
          onRetry={() => void query.refetch()}
          isRetrying={query.isFetching}
        />
      )}
      {query.isSuccess && query.data.results.length === 0 && (
        <p className="text-text-secondary text-sm">
          {hasFilters ? "No cases match this filter." : "This dataset has no cases yet."}
        </p>
      )}
      {query.isSuccess && query.data.results.length > 0 && (
        <>
          {/* Server ordering preserved (`dataset_id, key` — evaluations/models.py
              EvaluationCase.Meta.ordering), never client-sorted (master prompt
              Part C §13). */}
          <ol
            aria-label="Evaluation cases in this dataset"
            className={cn("flex flex-col", query.isFetching && "opacity-60")}
          >
            {query.data.results.map((evaluationCase) => (
              <CaseRow
                key={evaluationCase.id}
                evaluationCase={evaluationCase}
                canManage={canManage}
                workspaceId={workspaceId}
                datasetId={datasetId}
              />
            ))}
          </ol>
          <Pagination
            page={params.page}
            hasPrevious={query.data.previous !== null && query.data.previous !== undefined}
            hasNext={query.data.next !== null && query.data.next !== undefined}
            onPrevious={() => pushParams({ ...params, page: Math.max(1, params.page - 1) })}
            onNext={() => pushParams({ ...params, page: params.page + 1 })}
            summary={`Page ${params.page} · ${query.data.count} case${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

/**
 * "Start Run" action (Phase 23 Chunk 3), scoped to this dataset. Gated
 * `canRun`-only — hidden, not disabled, for a lower-privilege viewer (master
 * prompt Part D §15 RBAC-UI pattern) — but the backend's own
 * `CanRunEvaluations` permission (evaluations/permissions.py) is what
 * actually blocks a direct unauthorized API call regardless of what renders
 * here. A successful start navigates straight to the new run's detail page,
 * where its status is polled exactly like any other run (queries.ts
 * `pollWhileNonTerminalRun`) — no separate "started" toast to leak.
 */
function StartRunPanel({ workspaceId, datasetId }: { workspaceId: string; datasetId: string }) {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const mutation = useStartEvaluationRunMutation(workspaceId);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <Button size="sm" onClick={() => setIsOpen((open) => !open)} disabled={mutation.isPending}>
          {isOpen ? "Cancel" : "Start run"}
        </Button>
      </div>
      {isOpen && (
        <StartEvaluationRunForm
          workspaceId={workspaceId}
          isPending={mutation.isPending}
          error={mutation.isError ? mutation.error.message : null}
          onSubmit={(agentVersionId) => {
            if (mutation.isPending) {
              return;
            }
            mutation.mutate(
              { dataset_id: datasetId, agent_version_id: agentVersionId },
              {
                onSuccess: (run) => {
                  router.push(`/app/evaluations/${run.id}`);
                },
              },
            );
          }}
          onCancel={() => setIsOpen(false)}
        />
      )}
      {mutation.isError && !isOpen && (
        <Alert variant="danger" title="This evaluation run could not be started">
          {mutation.error.message}
        </Alert>
      )}
    </div>
  );
}

function EvaluationDatasetDetailContent({
  workspaceId,
  datasetId,
  canManage,
  canRun,
}: {
  workspaceId: string;
  datasetId: string;
  canManage: boolean;
  canRun: boolean;
}) {
  const datasetQuery = useEvaluationDatasetDetailQuery(workspaceId, datasetId);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const updateMutation = useUpdateEvaluationDatasetMutation(workspaceId, datasetId);

  if (datasetQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading evaluation dataset">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading evaluation dataset</span>
      </div>
    );
  }

  if (datasetQuery.isError) {
    if (datasetQuery.error.code === "not_found") {
      return <DatasetNotFound />;
    }
    return (
      <ListError
        message={datasetQuery.error.message}
        onRetry={() => void datasetQuery.refetch()}
        isRetrying={datasetQuery.isFetching}
      />
    );
  }

  const dataset = datasetQuery.data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link
          href="/app/evaluations?tab=datasets"
          className="text-primary-700 text-sm hover:underline"
        >
          ← Back to Datasets
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>{dataset.name}</CardTitle>
              <EvaluationDatasetStatusBadge status={dataset.status} />
            </div>
            {canManage && !isEditOpen && (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setIsEditOpen(true)}
              >
                Edit dataset
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {isEditOpen ? (
            <EvaluationDatasetForm
              mode="edit"
              initial={dataset}
              isPending={updateMutation.isPending}
              error={updateMutation.isError ? updateMutation.error.message : null}
              onSubmit={(input) => {
                if (updateMutation.isPending) {
                  return;
                }
                updateMutation.mutate(input, { onSuccess: () => setIsEditOpen(false) });
              }}
              onCancel={() => setIsEditOpen(false)}
            />
          ) : (
            <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {dataset.description && <Field label="Description" value={dataset.description} />}
              <Field label="Created" value={<Timestamp value={dataset.created_at} />} />
              <Field label="Updated" value={<Timestamp value={dataset.updated_at} />} />
            </dl>
          )}
          <p className="text-text-secondary text-xs">
            Editing this dataset or its cases only affects future evaluation runs. Every past
            evaluation run keeps executing against its own immutable case snapshot recorded at the
            time it was created — past results never change.
          </p>
        </CardContent>
      </Card>

      {canRun && (
        <Card>
          <CardHeader>
            <CardTitle>Run this dataset</CardTitle>
          </CardHeader>
          <CardContent>
            <StartRunPanel workspaceId={workspaceId} datasetId={datasetId} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Cases</CardTitle>
        </CardHeader>
        <CardContent>
          <Suspense
            fallback={
              <div role="status" aria-label="Loading cases">
                <Skeleton className="h-24 w-full" />
                <span className="sr-only">Loading cases</span>
              </div>
            }
          >
            <CasesPanel workspaceId={workspaceId} datasetId={datasetId} canManage={canManage} />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}

export function EvaluationDatasetDetailPage({ datasetId }: { datasetId: string }) {
  const workspace = useWorkspace();

  if (!isValidDatasetId(datasetId)) {
    return <DatasetNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  const canManage = canManageEvaluations(workspace.activeWorkspace.role);
  const canRun = canRunEvaluations(workspace.activeWorkspace.role);

  return (
    <EvaluationDatasetDetailContent
      workspaceId={workspace.activeWorkspace.id}
      datasetId={datasetId}
      canManage={canManage}
      canRun={canRun}
    />
  );
}
