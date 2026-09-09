/**
 * React Query hooks for the agent-runs domain. Same conventions as
 * features/tickets/queries.ts: workspace-scoped keys, and `placeholderData`
 * reused only when the previous successful query was for the SAME
 * workspace (never across a workspace switch).
 *
 * Polling strategy (master prompt Part C-14, Part F-27, Part K-52):
 * an AgentRun's own execution (LLM calls, tool round-trips, approval waits)
 * happens server-side/asynchronously — there is no push channel (no
 * WebSocket exists on the backend for this), so a non-terminal run's detail
 * and step trace are polled at a modest, fixed interval. The moment the
 * fetched run reaches a terminal status (`isTerminalRunStatus` — the exact
 * backend state machine, agents/models.py `AGENT_RUN_TERMINAL_STATUSES`),
 * polling stops for good: TanStack Query's `refetchInterval` callback reads
 * the *latest fetched data* each time, so a run that terminates between
 * polls stops being polled on the very next scheduling decision, not one
 * cycle late. The list is not polled — Chunk 1 is a detail-first workflow
 * (an operator opens one run to watch it); polling every row of a list would
 * be a much heavier, unjustified request volume for a lower-value signal.
 */
import { useQuery } from "@tanstack/react-query";

import {
  fetchAgentRunDetail,
  fetchAgentRunList,
  fetchAgentRunSteps,
} from "@/features/agent-runs/api";
import { agentRunKeys } from "@/features/agent-runs/query-keys";
import type {
  AgentRun,
  AgentRunListParams,
  AgentStep,
  PaginatedAgentRunList,
} from "@/features/agent-runs/types";
import { isTerminalRunStatus } from "@/features/agent-runs/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

/** Non-terminal runs are polled at this interval (ms) while the tab is visible. */
export const AGENT_RUN_POLL_INTERVAL_MS = 5000;

function isSameWorkspaceQuery(queryKey: readonly unknown[], workspaceId: string): boolean {
  return queryKey[1] === workspaceId;
}

export function useAgentRunListQuery(workspaceId: string | null, params: AgentRunListParams) {
  return useQuery<PaginatedAgentRunList, ApiError>({
    queryKey: agentRunKeys.list(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchAgentRunList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
    placeholderData: (previousData, previousQuery) => {
      if (workspaceId === null || !previousQuery) {
        return undefined;
      }
      return isSameWorkspaceQuery(previousQuery.queryKey, workspaceId) ? previousData : undefined;
    },
  });
}

/**
 * `refetchInterval` receives the query's latest state on every scheduling
 * decision (not just the render that set it up), so this correctly stops
 * polling the instant a fetch observes a terminal status — including across
 * a workspace switch, since a stale run's query is simply no longer the
 * active one being rendered (disjoint, workspace-scoped keys — see
 * query-keys.ts).
 */
export function pollWhileNonTerminal(query: { state: { data?: AgentRun } }): number | false {
  const status = query.state.data?.status;
  if (!status || isTerminalRunStatus(status)) {
    return false;
  }
  return AGENT_RUN_POLL_INTERVAL_MS;
}

export function useAgentRunDetailQuery(workspaceId: string | null, runId: string | null) {
  return useQuery<AgentRun, ApiError>({
    queryKey: agentRunKeys.detail(workspaceId ?? NO_WORKSPACE, runId ?? ""),
    queryFn: ({ signal }) => fetchAgentRunDetail(workspaceId as string, runId as string, signal),
    enabled: workspaceId !== null && runId !== null,
    refetchInterval: pollWhileNonTerminal,
    refetchIntervalInBackground: false,
  });
}

/**
 * `runStatus` is passed in from the sibling run-detail query rather than
 * re-derived from the steps response (which carries no run-level status
 * field) — see AgentRunDetailPage, which owns both queries. Re-evaluated on
 * every render, which is sufficient here: a render is exactly what a fresh
 * run-detail poll produces, so the moment the run turns terminal, the next
 * render passes a terminal `runStatus` and this stops scheduling further
 * step polls.
 */
export function useAgentRunStepsQuery(
  workspaceId: string | null,
  runId: string | null,
  runStatus: AgentRun["status"] | undefined,
) {
  const refetchInterval =
    runStatus && !isTerminalRunStatus(runStatus) ? AGENT_RUN_POLL_INTERVAL_MS : false;
  return useQuery<AgentStep[], ApiError>({
    queryKey: agentRunKeys.steps(workspaceId ?? NO_WORKSPACE, runId ?? ""),
    queryFn: ({ signal }) => fetchAgentRunSteps(workspaceId as string, runId as string, signal),
    enabled: workspaceId !== null && runId !== null,
    refetchInterval,
    refetchIntervalInBackground: false,
  });
}
