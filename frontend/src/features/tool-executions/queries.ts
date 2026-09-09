/**
 * React Query hooks for the tool-executions domain.
 *
 * Polling strategy (master prompt Part B §8): reuses the exact same
 * non-terminal-run condition as `useAgentRunStepsQuery`
 * (features/agent-runs/queries.ts) — one coherent policy, not an
 * independent interval. While the owning Agent Run is non-terminal, this
 * fetches the run's *entire* tool-execution list once per interval (a
 * single request), never one request per tool execution — so a run with
 * several tool calls in flight still produces exactly one additional
 * request per poll, not N. The catalog query is never polled: it is
 * code-owned, workspace-independent metadata that does not change while an
 * operator is looking at a run.
 */
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { fetchToolCatalog, fetchToolExecutionsForRun } from "@/features/tool-executions/api";
import { toolExecutionKeys } from "@/features/tool-executions/query-keys";
import type {
  PaginatedToolDefinitionList,
  PaginatedToolExecutionList,
  ToolDefinition,
} from "@/features/tool-executions/types";
import type { AgentRun } from "@/features/agent-runs/types";
import { isTerminalRunStatus } from "@/features/agent-runs/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";
export const TOOL_EXECUTION_POLL_INTERVAL_MS = 5000;

/**
 * `runStatus` comes from the sibling run-detail query (AgentRunDetailPage
 * owns it), exactly like `useAgentRunStepsQuery` — never re-derived from
 * this list's own data, which carries no run-level status field.
 */
export function useToolExecutionsForRunQuery(
  workspaceId: string | null,
  runId: string | null,
  runStatus: AgentRun["status"] | undefined,
) {
  const refetchInterval =
    runStatus && !isTerminalRunStatus(runStatus) ? TOOL_EXECUTION_POLL_INTERVAL_MS : false;
  return useQuery<PaginatedToolExecutionList, ApiError>({
    queryKey: toolExecutionKeys.forRun(workspaceId ?? NO_WORKSPACE, runId ?? ""),
    queryFn: ({ signal }) =>
      fetchToolExecutionsForRun(workspaceId as string, runId as string, signal),
    enabled: workspaceId !== null && runId !== null,
    refetchInterval,
    refetchIntervalInBackground: false,
  });
}

/** Global tool catalog, keyed for a lookup by `tool_definition_id`. Not polled. */
export function useToolCatalogQuery(workspaceId: string | null) {
  const query = useQuery<PaginatedToolDefinitionList, ApiError>({
    queryKey: toolExecutionKeys.catalog(workspaceId ?? NO_WORKSPACE),
    queryFn: ({ signal }) => fetchToolCatalog(workspaceId as string, signal),
    enabled: workspaceId !== null,
  });
  const results = query.data?.results;
  const byId: ReadonlyMap<string, ToolDefinition> = useMemo(
    () => new Map((results ?? []).map((tool) => [tool.id, tool])),
    [results],
  );
  return { ...query, byId };
}
