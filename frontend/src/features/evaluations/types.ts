/**
 * Evaluation domain types (Phase 23 Chunk 1: Evaluation Runs + Results
 * Foundation).
 *
 * Re-exported from the generated OpenAPI schema — `EvaluationRun` and
 * `EvaluationResult` are both fully server-derived
 * (`read_only_fields = fields`, see backend/evaluations/serializers.py), so
 * no write-shape narrowing is needed beyond the list-filter gap documented
 * in api.ts.
 *
 * Schema gap register (Phase 23 Chunk 1 — Category B, non-blocking):
 *
 * 1. `EvaluationRun.threshold_config` and `EvaluationResult.scorer_output`
 *    are generated as `unknown` — both are plain Django `JSONField`s with no
 *    fixed shape at the API layer (evaluations/models.py). Rendered via the
 *    shared `StructuredPayload` component (same treatment as every other
 *    domain's free-form JSON field — AgentStep.safe_metadata,
 *    ToolExecution.arguments_redacted/result_redacted), never destructured
 *    into named fields the frontend would have to guess the shape of.
 *
 * 2. `EvaluationResult.agent_run_id` and `EvaluationResult.replay_of_id` are
 *    generated as required `string` (uuid format) fields, but the underlying
 *    model columns are nullable (`agent_run = ForeignKey(..., null=True)`,
 *    `replay_of = ForeignKey(..., null=True)` — evaluations/models.py). The
 *    serializer declares them as plain (non-`allow_null`)
 *    `serializers.UUIDField(read_only=True)`, which DRF still renders as
 *    JSON `null` when the underlying attribute is `None` — a generated-type
 *    vs. actual-runtime-value mismatch, not a genuine non-nullable
 *    guarantee. `EvaluationResult` below re-types both as `string | null`
 *    explicitly so calling code cannot forget the null case (a case with no
 *    real `AgentRun` yet, or an original — non-replay — result with no
 *    `replay_of`).
 */
import type { components } from "@/types/api";

export type EvaluationRun = components["schemas"]["EvaluationRun"];
export type PaginatedEvaluationRunList = components["schemas"]["PaginatedEvaluationRunList"];
export type EvaluationRunStatusValue = components["schemas"]["EvaluationRunStatusEnum"];

export type EvaluationResult = Omit<
  components["schemas"]["EvaluationResult"],
  "agent_run_id" | "replay_of_id"
> & {
  agent_run_id: string | null;
  replay_of_id: string | null;
};
export type PaginatedEvaluationResultList = Omit<
  components["schemas"]["PaginatedEvaluationResultList"],
  "results"
> & { results: EvaluationResult[] };
export type EvaluationResultStatusValue = components["schemas"]["EvaluationResultStatusEnum"];
export type EvaluationFailureCodeValue = components["schemas"]["EvaluationFailureCodeEnum"];
export type EvaluationProviderModeValue = components["schemas"]["EvaluationProviderModeEnum"];

/** `"all"` omits the corresponding filter from the request entirely. */
export type EvaluationRunStatusFilter = "all" | EvaluationRunStatusValue;
export type EvaluationResultPassedFilter = "all" | "passed" | "failed";

/**
 * The backend's real terminal-status set (evaluations/models.py
 * `EVALUATION_RUN_TERMINAL_STATUSES`) — mirrored here rather than imported
 * (frontend/backend are separate deployables). A run in any other status is
 * non-terminal and eligible for polling (see queries.ts).
 */
export const EVALUATION_RUN_TERMINAL_STATUSES: ReadonlySet<EvaluationRunStatusValue> = new Set([
  "succeeded",
  "partial",
  "failed",
  "cancelled",
]);

export function isTerminalEvaluationRunStatus(status: EvaluationRunStatusValue): boolean {
  return EVALUATION_RUN_TERMINAL_STATUSES.has(status);
}

/**
 * The backend's real terminal-status set for a result
 * (evaluations/models.py `EVALUATION_RESULT_TERMINAL_STATUSES`).
 */
export const EVALUATION_RESULT_TERMINAL_STATUSES: ReadonlySet<EvaluationResultStatusValue> =
  new Set(["succeeded", "failed", "cancelled"]);

export function isTerminalEvaluationResultStatus(status: EvaluationResultStatusValue): boolean {
  return EVALUATION_RESULT_TERMINAL_STATUSES.has(status);
}

export interface EvaluationRunListParams {
  page: number;
  status: EvaluationRunStatusFilter;
}

export const DEFAULT_EVALUATION_RUN_LIST_PARAMS: EvaluationRunListParams = {
  page: 1,
  status: "all",
};

export interface EvaluationResultListParams {
  page: number;
  passed: EvaluationResultPassedFilter;
}

export const DEFAULT_EVALUATION_RESULT_LIST_PARAMS: EvaluationResultListParams = {
  page: 1,
  passed: "all",
};
