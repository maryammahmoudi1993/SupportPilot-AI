"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import {
  AgentRunStatusBadge,
  AgentStepStatusBadge,
} from "@/features/agent-runs/components/agent-run-badges";
import { useAgentRunDetailQuery, useAgentRunStepsQuery } from "@/features/agent-runs/queries";
import type { AgentStep } from "@/features/agent-runs/types";
import { useWorkspace } from "@/features/workspace/workspace-provider";
import { EntityNotFound } from "@/components/support/entity-not-found";
import { ListError } from "@/components/support/list-error";
import { Timestamp } from "@/components/support/timestamp";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isValidRunId(runId: string): boolean {
  return UUID_PATTERN.test(runId);
}

function RunNotFound() {
  return (
    <EntityNotFound
      title="Agent run not found"
      description="This agent run doesn't exist, or isn't available in your active workspace."
      backHref="/app/agent-runs"
      backLabel="Back to Agent Runs"
    />
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-text-muted text-xs font-medium uppercase">{label}</dt>
      <dd className="text-text-primary text-sm">{value}</dd>
    </div>
  );
}

/**
 * Tool execution input/output/safe_metadata payloads are untrusted data
 * (master prompt Part C-16/18): rendered as inert preformatted text inside a
 * bounded, independently scrollable box — never `dangerouslySetInnerHTML`,
 * never allowed to force page-level horizontal overflow.
 */
function SafeMetadata({ value }: { value: unknown }) {
  const isEmpty =
    value === null ||
    value === undefined ||
    (typeof value === "object" && !Object.keys(value as object).length);
  if (isEmpty) {
    return <span className="text-text-secondary text-xs">—</span>;
  }
  return (
    <pre className="bg-surface-2 border-border-subtle max-h-64 overflow-auto rounded-md border p-2 text-xs break-words whitespace-pre-wrap">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function StepRow({ step }: { step: AgentStep }) {
  return (
    <li className="border-border-subtle border-b py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-text-muted text-xs font-medium">#{step.sequence}</span>
        <span className="text-text-primary text-sm font-medium">{step.step_type}</span>
        <AgentStepStatusBadge status={step.status} />
        {step.latency_ms !== null && (
          <span className="text-text-secondary text-xs">{step.latency_ms}ms</span>
        )}
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {(step.provider || step.model) && (
          <Field
            label="Provider / model"
            value={[step.provider, step.model].filter(Boolean).join(" · ") || "—"}
          />
        )}
        {step.input_summary && <Field label="Input summary" value={step.input_summary} />}
        {step.output_summary && <Field label="Output summary" value={step.output_summary} />}
        {step.error_code && (
          <Field
            label="Error code"
            value={<span className="text-danger-700">{step.error_code}</span>}
          />
        )}
        {step.started_at && <Field label="Started" value={<Timestamp value={step.started_at} />} />}
        {step.completed_at && (
          <Field label="Completed" value={<Timestamp value={step.completed_at} />} />
        )}
      </dl>
      {step.safe_metadata !== undefined && (
        <div className="mt-2">
          <p className="text-text-muted text-xs font-medium uppercase">Safe metadata</p>
          <SafeMetadata value={step.safe_metadata} />
        </div>
      )}
    </li>
  );
}

function AgentRunDetailContent({ workspaceId, runId }: { workspaceId: string; runId: string }) {
  const runQuery = useAgentRunDetailQuery(workspaceId, runId);
  const stepsQuery = useAgentRunStepsQuery(workspaceId, runId, runQuery.data?.status);

  if (runQuery.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Loading agent run">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
        <span className="sr-only">Loading agent run</span>
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
        <Link href="/app/agent-runs" className="text-primary-700 text-sm hover:underline">
          ← Back to Agent Runs
        </Link>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>Run #{run.id.slice(0, 8)}</CardTitle>
            <AgentRunStatusBadge status={run.status} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Trigger" value={<span className="capitalize">{run.trigger}</span>} />
            <Field
              label="Conversation"
              value={
                run.conversation_id ? (
                  <Link
                    href={`/app/inbox/${run.conversation_id}`}
                    className="text-primary-700 hover:underline focus-visible:underline"
                  >
                    View originating conversation
                  </Link>
                ) : (
                  "— (not tied to a conversation)"
                )
              }
            />
            <Field
              label="Ticket"
              value={
                run.ticket_id ? (
                  <Link
                    href={`/app/tickets/${run.ticket_id}`}
                    className="text-primary-700 hover:underline focus-visible:underline"
                  >
                    View related ticket
                  </Link>
                ) : (
                  "— (not tied to a ticket)"
                )
              }
            />
            <Field label="Steps executed" value={run.step_count} />
            <Field label="Tool calls" value={run.tool_call_count} />
            <Field label="Model calls" value={run.model_call_count} />
            <Field label="Total tokens" value={run.total_tokens} />
            <Field
              label="Estimated cost"
              value={run.estimated_cost_usd !== null ? `$${run.estimated_cost_usd}` : "—"}
            />
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

          {run.failure_code && (
            <div className="border-danger-200 bg-danger-50 rounded-md border p-3">
              <p className="text-danger-700 text-xs font-medium uppercase">Failure</p>
              <p className="text-danger-700 mt-1 text-sm">
                {run.failure_message_safe || "This run failed."}
              </p>
              <p className="text-danger-700 mt-1 text-xs">Code: {run.failure_code}</p>
            </div>
          )}

          {run.final_response && (
            <dl>
              <dt className="text-text-muted text-xs font-medium uppercase">Final response</dt>
              <dd className="text-text-primary mt-1 text-sm break-words whitespace-pre-wrap">
                {run.final_response}
              </dd>
            </dl>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Execution trace</CardTitle>
        </CardHeader>
        <CardContent>
          {stepsQuery.isPending && (
            <div role="status" aria-label="Loading execution trace">
              <Skeleton className="h-24 w-full" />
              <span className="sr-only">Loading execution trace</span>
            </div>
          )}
          {stepsQuery.isError && (
            <ListError
              message={stepsQuery.error.message}
              onRetry={() => void stepsQuery.refetch()}
              isRetrying={stepsQuery.isFetching}
            />
          )}
          {stepsQuery.isSuccess && stepsQuery.data.length === 0 && (
            <p className="text-text-secondary text-sm">No trace steps recorded for this run.</p>
          )}
          {stepsQuery.isSuccess && stepsQuery.data.length > 0 && (
            <ol aria-label="Agent run execution steps" className="flex flex-col">
              {stepsQuery.data.map((step) => (
                <StepRow key={step.id} step={step} />
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function AgentRunDetailPage({ runId }: { runId: string }) {
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

  return <AgentRunDetailContent workspaceId={workspace.activeWorkspace.id} runId={runId} />;
}
