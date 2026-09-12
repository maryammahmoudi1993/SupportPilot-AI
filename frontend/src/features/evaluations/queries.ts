/**
 * React Query hooks for the evaluations domain. Same conventions as
 * features/agent-runs/queries.ts: workspace-scoped keys, and
 * `placeholderData` reused only when the previous successful query was for
 * the SAME workspace (never across a workspace switch).
 *
 * Polling strategy (master prompt Part H §30): an EvaluationRun executes
 * asynchronously server-side (evaluations/tasks.py, Celery) — there is no
 * push channel, so a non-terminal run's detail is polled at a modest, fixed
 * interval, exactly mirroring `pollWhileNonTerminal` in
 * features/agent-runs/queries.ts. The moment the fetched run reaches a
 * terminal status (`isTerminalEvaluationRunStatus` — the exact backend state
 * machine, evaluations/models.py `EVALUATION_RUN_TERMINAL_STATUSES`),
 * polling stops for good. The results list is polled using the same
 * non-terminal condition, driven by the sibling run-detail query's status
 * (passed in by the caller, never re-derived from the results response
 * itself, which carries no run-level status field) — one bounded list
 * request per interval, never one request per result (no N+1). The run list
 * is not polled — Chunk 1 is a detail-first workflow (an operator opens one
 * run to watch it), matching agent-runs' own list-polling decision.
 */
import { useQuery } from "@tanstack/react-query";

import {
  fetchAgentDefinitionOptions,
  fetchAgentVersionOptions,
  fetchEvaluationCaseList,
  fetchEvaluationDatasetDetail,
  fetchEvaluationDatasetList,
  fetchEvaluationResultList,
  fetchEvaluationRunDetail,
  fetchEvaluationRunList,
} from "@/features/evaluations/api";
import { evaluationKeys } from "@/features/evaluations/query-keys";
import type {
  AgentDefinitionOption,
  AgentVersionOption,
  EvaluationCaseListParams,
  EvaluationDataset,
  EvaluationDatasetListParams,
  EvaluationResultListParams,
  EvaluationRun,
  EvaluationRunListParams,
  PaginatedEvaluationCaseList,
  PaginatedEvaluationDatasetList,
  PaginatedEvaluationResultList,
  PaginatedEvaluationRunList,
} from "@/features/evaluations/types";
import { isTerminalEvaluationRunStatus } from "@/features/evaluations/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";

/** Non-terminal runs (and their results list) are polled at this interval (ms). */
export const EVALUATION_RUN_POLL_INTERVAL_MS = 5000;

function isSameWorkspaceQuery(queryKey: readonly unknown[], workspaceId: string): boolean {
  return queryKey[1] === workspaceId;
}

export function useEvaluationRunListQuery(
  workspaceId: string | null,
  params: EvaluationRunListParams,
) {
  return useQuery<PaginatedEvaluationRunList, ApiError>({
    queryKey: evaluationKeys.runList(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchEvaluationRunList(workspaceId as string, params, signal),
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
 * decision, so this correctly stops polling the instant a fetch observes a
 * terminal status — including across a workspace switch, since a stale
 * run's query is simply no longer the active one being rendered (disjoint,
 * workspace-scoped keys — see query-keys.ts).
 */
export function pollWhileNonTerminalRun(query: {
  state: { data?: EvaluationRun };
}): number | false {
  const status = query.state.data?.status;
  if (!status || isTerminalEvaluationRunStatus(status)) {
    return false;
  }
  return EVALUATION_RUN_POLL_INTERVAL_MS;
}

export function useEvaluationRunDetailQuery(workspaceId: string | null, runId: string | null) {
  return useQuery<EvaluationRun, ApiError>({
    queryKey: evaluationKeys.runDetail(workspaceId ?? NO_WORKSPACE, runId ?? ""),
    queryFn: ({ signal }) =>
      fetchEvaluationRunDetail(workspaceId as string, runId as string, signal),
    enabled: workspaceId !== null && runId !== null,
    refetchInterval: pollWhileNonTerminalRun,
    refetchIntervalInBackground: false,
  });
}

/**
 * `runStatus` is passed in from the sibling run-detail query rather than
 * re-derived from the results response, exactly like
 * `useAgentRunStepsQuery`/`useToolExecutionsForRunQuery`.
 */
export function useEvaluationResultListQuery(
  workspaceId: string | null,
  runId: string | null,
  runStatus: EvaluationRun["status"] | undefined,
  params: EvaluationResultListParams,
) {
  const refetchInterval =
    runStatus && !isTerminalEvaluationRunStatus(runStatus)
      ? EVALUATION_RUN_POLL_INTERVAL_MS
      : false;
  return useQuery<PaginatedEvaluationResultList, ApiError>({
    queryKey: evaluationKeys.resultList(workspaceId ?? NO_WORKSPACE, runId ?? "", params),
    queryFn: ({ signal }) =>
      fetchEvaluationResultList(workspaceId as string, runId as string, params, signal),
    enabled: workspaceId !== null && runId !== null,
    refetchInterval,
    refetchIntervalInBackground: false,
    placeholderData: (previousData, previousQuery) => {
      if (workspaceId === null || runId === null || !previousQuery) {
        return undefined;
      }
      return isSameWorkspaceQuery(previousQuery.queryKey, workspaceId) ? previousData : undefined;
    },
  });
}

/** Datasets/Cases (Phase 23 Chunk 2). No polling: dataset/case content only
 * changes on an explicit operator write, never asynchronously. */
export function useEvaluationDatasetListQuery(
  workspaceId: string | null,
  params: EvaluationDatasetListParams,
) {
  return useQuery<PaginatedEvaluationDatasetList, ApiError>({
    queryKey: evaluationKeys.datasetList(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchEvaluationDatasetList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
    placeholderData: (previousData, previousQuery) => {
      if (workspaceId === null || !previousQuery) {
        return undefined;
      }
      return isSameWorkspaceQuery(previousQuery.queryKey, workspaceId) ? previousData : undefined;
    },
  });
}

export function useEvaluationDatasetDetailQuery(
  workspaceId: string | null,
  datasetId: string | null,
) {
  return useQuery<EvaluationDataset, ApiError>({
    queryKey: evaluationKeys.datasetDetail(workspaceId ?? NO_WORKSPACE, datasetId ?? ""),
    queryFn: ({ signal }) =>
      fetchEvaluationDatasetDetail(workspaceId as string, datasetId as string, signal),
    enabled: workspaceId !== null && datasetId !== null,
  });
}

/**
 * Agent-version picker support for "Start Run" (Phase 23 Chunk 3). Neither
 * query polls — the picker is opened on demand and its options only change
 * on an explicit admin write elsewhere, never asynchronously mid-form.
 */
export function useAgentDefinitionOptionsQuery(workspaceId: string | null, enabled: boolean) {
  return useQuery<AgentDefinitionOption[], ApiError>({
    queryKey: evaluationKeys.agentDefinitionOptions(workspaceId ?? NO_WORKSPACE),
    queryFn: ({ signal }) => fetchAgentDefinitionOptions(workspaceId as string, signal),
    enabled: workspaceId !== null && enabled,
  });
}

export function useAgentVersionOptionsQuery(
  workspaceId: string | null,
  agentId: string | null,
  enabled: boolean,
) {
  return useQuery<AgentVersionOption[], ApiError>({
    queryKey: evaluationKeys.agentVersionOptions(workspaceId ?? NO_WORKSPACE, agentId ?? ""),
    queryFn: ({ signal }) =>
      fetchAgentVersionOptions(workspaceId as string, agentId as string, signal),
    enabled: workspaceId !== null && agentId !== null && enabled,
  });
}

export function useEvaluationCaseListQuery(
  workspaceId: string | null,
  datasetId: string | null,
  params: EvaluationCaseListParams,
) {
  return useQuery<PaginatedEvaluationCaseList, ApiError>({
    queryKey: evaluationKeys.caseList(workspaceId ?? NO_WORKSPACE, datasetId ?? "", params),
    queryFn: ({ signal }) =>
      fetchEvaluationCaseList(workspaceId as string, datasetId as string, params, signal),
    enabled: workspaceId !== null && datasetId !== null,
    placeholderData: (previousData, previousQuery) => {
      if (workspaceId === null || datasetId === null || !previousQuery) {
        return undefined;
      }
      return isSameWorkspaceQuery(previousQuery.queryKey, workspaceId) ? previousData : undefined;
    },
  });
}
