"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";

import {
  EvaluationPassedBadge,
  EvaluationResultStatusBadge,
  EvaluationRunStatusBadge,
} from "@/features/evaluations/components/evaluation-badges";
import {
  useCancelEvaluationRunMutation,
  useReplayEvaluationResultMutation,
} from "@/features/evaluations/mutations";
import {
  useEvaluationResultListQuery,
  useEvaluationRunDetailQuery,
} from "@/features/evaluations/queries";
import type {
  EvaluationResult,
  EvaluationResultListParams,
  EvaluationResultPassedFilter,
  EvaluationRunStatusValue,
} from "@/features/evaluations/types";
import {
  canRunEvaluations,
  isTerminalEvaluationResultStatus,
  isTerminalEvaluationRunStatus,
} from "@/features/evaluations/types";
import {
  buildEvaluationResultListQueryString,
  parseEvaluationResultListParams,
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
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidRunId(runId: string): boolean {
  return UUID_PATTERN.test(runId);
}

function RunNotFound() {
  return (
    <EntityNotFound
      title="Evaluation run not found"
      description="This evaluation run doesn't exist, or isn't available in your active workspace."
      backHref="/app/evaluations"
      backLabel="Back to Evaluations"
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

const RESULT_PASSED_OPTIONS: { value: EvaluationResultPassedFilter; label: string }[] = [
  { value: "all", label: "All outcomes" },
  { value: "passed", label: "Passed" },
  { value: "failed", label: "Failed" },
];

/**
 * Replay control (Phase 23 Chunk 3, evaluations/views.py
 * `EvaluationResultReplayView` / services.py `replay_evaluation_case`): only
 * offered for a result already in a terminal status — the backend rejects
 * (409) replaying a still-`pending`/`running` result outright
 * (`EvaluationResultNotReplayableError`), so the control mirrors that rather
 * than letting an operator hit a guaranteed conflict. A replay never mutates
 * this result; it creates a brand-new sibling result referencing the same
 * case snapshot (`replay_of_id`), which the results list picks up on its own
 * next poll/refetch (invalidated on success) — never spliced in locally.
 */
function ReplayResultControl({
  workspaceId,
  runId,
  result,
}: {
  workspaceId: string;
  runId: string;
  result: EvaluationResult;
}) {
  const mutation = useReplayEvaluationResultMutation(workspaceId, runId);

  if (!isTerminalEvaluationResultStatus(result.status)) {
    return null;
  }

  return (
    <div className="mt-2 flex flex-col gap-2">
      <div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => {
            if (mutation.isPending) {
              return;
            }
            mutation.mutate(result.id);
          }}
          disabled={mutation.isPending}
          isLoading={mutation.isPending}
        >
          Replay
        </Button>
      </div>
      {mutation.isError && (
        <Alert variant="danger" title="This result could not be replayed">
          {mutation.error.message}
        </Alert>
      )}
      {mutation.isSuccess && <Alert variant="success">Replay queued as a new result.</Alert>}
    </div>
  );
}

function ResultRow({
  result,
  workspaceId,
  runId,
  canRun,
}: {
  result: EvaluationResult;
  workspaceId: string;
  runId: string;
  canRun: boolean;
}) {
  return (
    <li className="border-border-subtle border-b py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-text-primary text-sm font-medium">{result.case_key}</span>
        <EvaluationResultStatusBadge status={result.status} />
        <EvaluationPassedBadge passed={result.passed} />
        {result.replay_of_id !== null && (
          <span className="text-text-secondary text-xs">Replay</span>
        )}
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Field
          label="Agent run"
          value={
            result.agent_run_id !== null ? (
              <Link
                href={`/app/agent-runs/${result.agent_run_id}`}
                className="text-primary-700 hover:underline focus-visible:underline"
              >
                View agent run
              </Link>
            ) : (
              "— (no agent run recorded)"
            )
          }
        />
        {result.latency_ms !== null && <Field label="Latency" value={`${result.latency_ms}ms`} />}
        <Field label="Total tokens" value={result.total_tokens} />
        <Field
          label="Estimated cost"
          value={result.estimated_cost_usd !== null ? `$${result.estimated_cost_usd}` : "—"}
        />
        {result.failure_code && <Field label="Failure code" value={result.failure_code} />}
        {result.failure_message_safe && (
          <Field label="Failure message" value={result.failure_message_safe} />
        )}
        {result.started_at && (
          <Field label="Started" value={<Timestamp value={result.started_at} />} />
        )}
        {result.completed_at && (
          <Field label="Completed" value={<Timestamp value={result.completed_at} />} />
        )}
      </dl>
      <div className="mt-2">
        <StructuredPayload value={result.scorer_output} label="Scorer output" />
      </div>
      {canRun && <ReplayResultControl workspaceId={workspaceId} runId={runId} result={result} />}
    </li>
  );
}

function ResultsPanel({
  workspaceId,
  runId,
  runStatus,
  canRun,
}: {
  workspaceId: string;
  runId: string;
  runStatus: EvaluationRunStatusValue;
  canRun: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const params = parseEvaluationResultListParams(searchParams);
  const query = useEvaluationResultListQuery(workspaceId, runId, runStatus, params);

  function pushParams(next: EvaluationResultListParams) {
    router.replace(`${pathname}${buildEvaluationResultListQueryString(next)}`, { scroll: false });
  }

  function handlePassedChange(event: ChangeEvent<HTMLSelectElement>) {
    pushParams({ ...params, passed: event.target.value as EvaluationResultPassedFilter, page: 1 });
  }

  const hasFilters = params.passed !== "all";

  return (
    <div className="flex flex-col gap-4">
      <div className="w-full sm:w-56">
        <Label htmlFor="evaluation-result-passed-filter">Outcome</Label>
        <select
          id="evaluation-result-passed-filter"
          value={params.passed}
          onChange={handlePassedChange}
          className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
        >
          {RESULT_PASSED_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {query.isPending && (
        <div role="status" aria-label="Loading results">
          <Skeleton className="h-24 w-full" />
          <span className="sr-only">Loading results</span>
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
          {hasFilters ? "No results match this filter." : "No per-case results recorded yet."}
        </p>
      )}
      {query.isSuccess && query.data.results.length > 0 && (
        <>
          <ol
            aria-label="Evaluation case results"
            className={cn("flex flex-col", query.isFetching && "opacity-60")}
          >
            {query.data.results.map((result) => (
              <ResultRow
                key={result.id}
                result={result}
                workspaceId={workspaceId}
                runId={runId}
                canRun={canRun}
              />
            ))}
          </ol>
          <Pagination
            page={params.page}
            hasPrevious={query.data.previous !== null && query.data.previous !== undefined}
            hasNext={query.data.next !== null && query.data.next !== undefined}
            onPrevious={() => pushParams({ ...params, page: Math.max(1, params.page - 1) })}
            onNext={() => pushParams({ ...params, page: params.page + 1 })}
            summary={`Page ${params.page} · ${query.data.count} result${query.data.count === 1 ? "" : "s"} total`}
          />
        </>
      )}
    </div>
  );
}

/**
 * Cancel control (Phase 23 Chunk 3, evaluations/views.py
 * `EvaluationRunCancelView` / services.py `cancel_evaluation_run`): only
 * rendered for a non-terminal run — the backend independently re-validates
 * this and returns 409 for an already-terminal run
 * (`EvaluationRunNotCancellableError`), confirmed by
 * `test_trigger_run_then_read_results_and_cancel`'s "cancel again is 409"
 * assertion. A confirmation dialog gates the action (master prompt Part J
 * §38-39: no destructive/state-changing action fires on a single click) —
 * unlike webhook redrive, cancelling is NOT an at-least-once/duplicable
 * external side effect, so the copy is a plain, accurate description of
 * what happens, not a duplicate-effect warning.
 */
function CancelRunControl({
  workspaceId,
  runId,
  status,
}: {
  workspaceId: string;
  runId: string;
  status: EvaluationRunStatusValue;
}) {
  const mutation = useCancelEvaluationRunMutation(workspaceId, runId);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const isCancellable = !isTerminalEvaluationRunStatus(status);

  if (!isCancellable && !mutation.isSuccess) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2">
      {isCancellable && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => setConfirmOpen(true)}
          disabled={mutation.isPending}
          isLoading={mutation.isPending}
        >
          Cancel run
        </Button>
      )}
      {mutation.isError && (
        <Alert variant="danger" title="This run could not be cancelled">
          {mutation.error.message}
        </Alert>
      )}
      {mutation.isSuccess && <Alert variant="success">Evaluation run cancelled.</Alert>}
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Cancel this evaluation run?"
        description="Any still-pending case in this run is cancelled outright. A case already running is left to finish, but the run itself moves to Cancelled and will not start any further cases."
        confirmLabel="Cancel run"
        confirmVariant="danger"
        onConfirm={() => mutation.mutate(undefined, { onSettled: () => setConfirmOpen(false) })}
        isConfirming={mutation.isPending}
      />
    </div>
  );
}

function EvaluationRunDetailContent({
  workspaceId,
  runId,
  canRun,
}: {
  workspaceId: string;
  runId: string;
  canRun: boolean;
}) {
  const runQuery = useEvaluationRunDetailQuery(workspaceId, runId);

  if (runQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading evaluation run">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading evaluation run</span>
      </div>
    );
  }

  if (runQuery.isError) {
    if (runQuery.error.code === "not_found") {
      return <RunNotFound />;
    }
    return (
      <ListError
        message={runQuery.error.message}
        onRetry={() => void runQuery.refetch()}
        isRetrying={runQuery.isFetching}
      />
    );
  }

  const run = runQuery.data;

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link href="/app/evaluations" className="text-primary-700 text-sm hover:underline">
          ← Back to Evaluations
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>Run #{run.id.slice(0, 8)}</CardTitle>
              <EvaluationRunStatusBadge status={run.status} />
            </div>
            {canRun && (
              <CancelRunControl workspaceId={workspaceId} runId={runId} status={run.status} />
            )}
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Provider mode" value={run.provider_mode} />
            <Field label="Dataset" value={run.dataset_id} />
            <Field label="Agent version" value={run.agent_version_id} />
            <Field label="Total cases" value={run.total_cases} />
            <Field label="Completed cases" value={run.completed_cases} />
            <Field label="Passed cases" value={run.passed_cases} />
            <Field label="Failed cases" value={run.failed_cases} />
            <Field label="Created" value={<Timestamp value={run.created_at} />} />
            <Field
              label="Started"
              value={run.started_at ? <Timestamp value={run.started_at} /> : "—"}
            />
            <Field
              label="Completed"
              value={run.completed_at ? <Timestamp value={run.completed_at} /> : "—"}
            />
            <Field
              label="Cancelled"
              value={run.cancelled_at ? <Timestamp value={run.cancelled_at} /> : "—"}
            />
          </dl>

          <div>
            <StructuredPayload value={run.threshold_config} label="Threshold configuration" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Case results</CardTitle>
        </CardHeader>
        <CardContent>
          <Suspense
            fallback={
              <div role="status" aria-label="Loading results">
                <Skeleton className="h-24 w-full" />
                <span className="sr-only">Loading results</span>
              </div>
            }
          >
            <ResultsPanel
              workspaceId={workspaceId}
              runId={runId}
              runStatus={run.status}
              canRun={canRun}
            />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}

export function EvaluationRunDetailPage({ runId }: { runId: string }) {
  const workspace = useWorkspace();

  if (!isValidRunId(runId)) {
    return <RunNotFound />;
  }

  if (workspace.status !== "ready" || !workspace.activeWorkspace) {
    return (
      <div className="flex flex-1 items-center justify-center py-16">
        <Spinner label="Loading your workspace" />
      </div>
    );
  }

  return (
    <EvaluationRunDetailContent
      workspaceId={workspace.activeWorkspace.id}
      runId={runId}
      canRun={canRunEvaluations(workspace.activeWorkspace.role)}
    />
  );
}
