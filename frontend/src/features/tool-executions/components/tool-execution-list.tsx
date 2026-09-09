"use client";

import type { ReactNode } from "react";

import {
  ApprovalContextNote,
  RiskLevelBadge,
  SideEffectBadge,
  ToolExecutionStatusBadge,
} from "@/features/tool-executions/components/tool-execution-badges";
import {
  useToolCatalogQuery,
  useToolExecutionsForRunQuery,
} from "@/features/tool-executions/queries";
import type {
  RiskLevelValue,
  SideEffectTypeValue,
  ToolExecution,
} from "@/features/tool-executions/types";
import { deriveApprovalContext } from "@/features/tool-executions/types";
import type { AgentRun } from "@/features/agent-runs/types";
import { ListError } from "@/components/support/list-error";
import { StructuredPayload } from "@/components/support/structured-payload";
import { Timestamp } from "@/components/support/timestamp";
import { Skeleton } from "@/components/ui/skeleton";

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-text-muted text-xs font-medium uppercase">{label}</dt>
      <dd className="text-text-primary text-sm">{value}</dd>
    </div>
  );
}

function ToolExecutionRow({
  execution,
  toolDisplayName,
  riskLevel,
  sideEffectType,
}: {
  execution: ToolExecution;
  toolDisplayName: string | null;
  riskLevel: RiskLevelValue | null;
  sideEffectType: SideEffectTypeValue | null;
}) {
  const approvalContext = deriveApprovalContext(execution);

  return (
    <li className="border-border-subtle border-b py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-text-primary text-sm font-medium">
          {toolDisplayName ?? execution.tool_key}
        </span>
        <ToolExecutionStatusBadge status={execution.status} />
        {riskLevel && <RiskLevelBadge level={riskLevel} />}
        {sideEffectType && <SideEffectBadge type={sideEffectType} />}
        <ApprovalContextNote context={approvalContext} />
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {toolDisplayName && toolDisplayName !== execution.tool_key && (
          <Field label="Tool key" value={execution.tool_key} />
        )}
        <Field label="Attempts" value={execution.attempt_count} />
        <Field label="Timeout" value={`${execution.timeout_seconds}s`} />
        {execution.duration_ms !== null && (
          <Field label="Duration" value={`${execution.duration_ms}ms`} />
        )}
        {execution.idempotency_key && (
          <Field label="Idempotency key" value={execution.idempotency_key} />
        )}
        {execution.started_at && (
          <Field label="Started" value={<Timestamp value={execution.started_at} />} />
        )}
        {execution.completed_at && (
          <Field label="Completed" value={<Timestamp value={execution.completed_at} />} />
        )}
        {execution.error_code && (
          <Field
            label="Error code"
            value={<span className="text-danger-700">{execution.error_code}</span>}
          />
        )}
      </dl>
      {execution.error_message_safe && (
        <p className="text-danger-700 mt-2 text-sm">{execution.error_message_safe}</p>
      )}
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <StructuredPayload value={execution.arguments_redacted} label="Arguments" />
        <StructuredPayload value={execution.result_redacted} label="Result" />
      </div>
    </li>
  );
}

/**
 * Embedded inside Agent Run detail (master prompt Part B §6) rather than a
 * standalone route — see frontend/README.md, "Tool Executions" for the
 * documented decision. Renders exactly the order the backend list endpoint
 * returns (`-created_at, -id` — tools/selectors.py
 * `tool_execution_list_for_workspace`); never client-sorted.
 */
export function ToolExecutionList({
  workspaceId,
  runId,
  runStatus,
}: {
  workspaceId: string;
  runId: string;
  runStatus: AgentRun["status"];
}) {
  const executionsQuery = useToolExecutionsForRunQuery(workspaceId, runId, runStatus);
  const catalogQuery = useToolCatalogQuery(workspaceId);

  if (executionsQuery.isPending) {
    return (
      <div role="status" aria-label="Loading tool executions">
        <Skeleton className="h-16 w-full" />
        <span className="sr-only">Loading tool executions</span>
      </div>
    );
  }

  if (executionsQuery.isError) {
    return (
      <ListError
        message={executionsQuery.error.message}
        onRetry={() => void executionsQuery.refetch()}
        isRetrying={executionsQuery.isFetching}
      />
    );
  }

  if (executionsQuery.data.results.length === 0) {
    return <p className="text-text-secondary text-sm">No tool executions recorded for this run.</p>;
  }

  return (
    <ol aria-label="Tool executions" className="flex flex-col">
      {executionsQuery.data.results.map((execution) => {
        const tool = catalogQuery.byId.get(execution.tool_definition_id);
        return (
          <ToolExecutionRow
            key={execution.id}
            execution={execution}
            toolDisplayName={tool?.display_name ?? null}
            riskLevel={tool?.risk_level ?? null}
            sideEffectType={tool?.side_effect_type ?? null}
          />
        );
      })}
    </ol>
  );
}
