/**
 * Typed, workspace-scoped query key factory for the evaluations domain —
 * same policy as every other domain (see features/agent-runs/query-keys.ts):
 * every key embeds the workspace ID as its second segment, so a workspace
 * switch produces a disjoint cache entry, never a stale one another
 * workspace could render.
 *
 * `results` is nested under the run it belongs to (mirroring
 * `agentRunKeys.steps`/`toolExecutionKeys.forRun`) since every real use in
 * this chunk is "the results for one Evaluation Run".
 */
import type {
  EvaluationResultListParams,
  EvaluationRunListParams,
} from "@/features/evaluations/types";

export const evaluationKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "evaluations"] as const,
  runsAll: (workspaceId: string) => [...evaluationKeys.all(workspaceId), "runs"] as const,
  runLists: (workspaceId: string) => [...evaluationKeys.runsAll(workspaceId), "list"] as const,
  runList: (workspaceId: string, params: EvaluationRunListParams) =>
    [...evaluationKeys.runLists(workspaceId), params] as const,
  runDetails: (workspaceId: string) => [...evaluationKeys.runsAll(workspaceId), "detail"] as const,
  runDetail: (workspaceId: string, runId: string) =>
    [...evaluationKeys.runDetails(workspaceId), runId] as const,
  results: (workspaceId: string, runId: string) =>
    [...evaluationKeys.runDetail(workspaceId, runId), "results"] as const,
  resultList: (workspaceId: string, runId: string, params: EvaluationResultListParams) =>
    [...evaluationKeys.results(workspaceId, runId), "list", params] as const,
};
