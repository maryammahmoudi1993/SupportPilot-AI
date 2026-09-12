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

/**
 * Dataset/Case domain types (Phase 23 Chunk 2: Evaluation Datasets + Cases
 * Management).
 *
 * Schema gap register additions (Phase 23 Chunk 2 — Category B, non-blocking):
 *
 * 4. `EvaluationCase.status` / `EvaluationCaseWrite.status` /
 *    `PatchedEvaluationCaseWrite.status` are generated as
 *    `WebhookEndpointStatusEnum` rather than a case-specific enum name —
 *    drf-spectacular's component-naming collision (identical to the
 *    `ToolDefinition.status` gap documented in
 *    features/tool-executions/types.ts): both real enums are the same
 *    two-value `"active" | "disabled"` shape (evaluations/models.py
 *    `EvaluationCaseStatus`), so the values are correct, only the generated
 *    TypeScript name is confusing. Re-typed below as
 *    `EvaluationCaseStatusValue`.
 *
 * 5. `evaluations_datasets_create` and `evaluations_datasets_cases_create`
 *    both generate their 201 response as the *request* write shape
 *    (`EvaluationDatasetWrite` / `EvaluationCaseWrite`) instead of the real
 *    full body the view actually returns (`evaluations/views.py` —
 *    `EvaluationDatasetListCreateView.create` /
 *    `EvaluationCaseListCreateView.create` both call
 *    `Response(<ReadSerializer>(obj).data, status=201)`, i.e. the same full
 *    `EvaluationDataset`/`EvaluationCase` shape as the read endpoints). Same
 *    generated-schema deficiency already documented for Integrations'
 *    `integrations_create` gap. `createEvaluationDataset`/`createEvaluationCase`
 *    in api.ts declare the real return type explicitly rather than trusting
 *    the generated 201 response type.
 *
 * 6. `EvaluationCaseWrite`/`PatchedEvaluationCaseWrite` both generate `key`
 *    as a writable field, but `evaluations/services.py
 *    update_evaluation_case` only ever reads
 *    `("name", "status", "input_message", "seeded_context", "expectations")`
 *    from the PATCH payload — `key` is silently ignored on update, never
 *    applied and never rejected (verified directly against the service, not
 *    inferred). `key` is therefore treated as create-only in this chunk's
 *    UI: the edit form never offers to change it, and shows it as read-only
 *    text instead of an editable field, so the UI never implies a no-op
 *    write would succeed.
 */
export type EvaluationDataset = components["schemas"]["EvaluationDataset"];
export type PaginatedEvaluationDatasetList =
  components["schemas"]["PaginatedEvaluationDatasetList"];
export type EvaluationDatasetStatusValue = components["schemas"]["EvaluationDatasetStatusEnum"];

export type EvaluationCaseStatusValue = "active" | "disabled";
export type EvaluationCase = Omit<components["schemas"]["EvaluationCase"], "status"> & {
  status: EvaluationCaseStatusValue;
};
export type PaginatedEvaluationCaseList = Omit<
  components["schemas"]["PaginatedEvaluationCaseList"],
  "results"
> & { results: EvaluationCase[] };

/** `"all"` omits the corresponding filter from the request entirely. */
export type EvaluationDatasetStatusFilter = "all" | EvaluationDatasetStatusValue;
export type EvaluationCaseStatusFilter = "all" | EvaluationCaseStatusValue;

export interface EvaluationDatasetListParams {
  page: number;
  status: EvaluationDatasetStatusFilter;
}

export const DEFAULT_EVALUATION_DATASET_LIST_PARAMS: EvaluationDatasetListParams = {
  page: 1,
  status: "all",
};

export interface EvaluationCaseListParams {
  page: number;
  status: EvaluationCaseStatusFilter;
}

export const DEFAULT_EVALUATION_CASE_LIST_PARAMS: EvaluationCaseListParams = {
  page: 1,
  status: "all",
};

export interface CreateEvaluationDatasetInput {
  name: string;
  description?: string;
  status?: EvaluationDatasetStatusValue;
}

export interface UpdateEvaluationDatasetInput {
  name?: string;
  description?: string;
  status?: EvaluationDatasetStatusValue;
}

export interface CreateEvaluationCaseInput {
  key: string;
  name: string;
  status?: EvaluationCaseStatusValue;
  input_message: string;
  seeded_context?: unknown;
  expectations?: unknown;
}

/** `key` deliberately absent — see schema gap 6 above: the backend never applies it on update. */
export interface UpdateEvaluationCaseInput {
  name?: string;
  status?: EvaluationCaseStatusValue;
  input_message?: string;
  seeded_context?: unknown;
  expectations?: unknown;
}

/**
 * Dataset/case management roles (evaluations/permissions.py
 * `EVALUATION_MANAGE_ROLES` — owner/admin/support_manager). Mirrored here
 * as UX-only gating (master prompt Part D §15): the backend
 * `CanManageEvaluations` permission is the sole authority — this only
 * controls whether a write control renders, never whether a request
 * succeeds.
 */
const EVALUATION_MANAGE_ROLES = new Set(["owner", "admin", "support_manager"]);

export function canManageEvaluations(role: string | undefined): boolean {
  return role !== undefined && EVALUATION_MANAGE_ROLES.has(role);
}

/**
 * Run execution/cancel/replay/compare roles (Phase 23 Chunk 3 —
 * evaluations/permissions.py `EVALUATION_RUN_ROLES`). Today this is the
 * exact same role set as `EVALUATION_MANAGE_ROLES` (the backend defines it
 * as `EVALUATION_MANAGE_ROLES` verbatim, not merely an identical literal),
 * but kept as its own function/permission concept since manage (dataset/case
 * writes) and run (execute/cancel/replay/compare) are documented as
 * logically distinct capabilities that could diverge independently — mirrors
 * the backend's own separate `CanManageEvaluations`/`CanRunEvaluations`
 * permission classes.
 */
const EVALUATION_RUN_ROLES = new Set(["owner", "admin", "support_manager"]);

export function canRunEvaluations(role: string | undefined): boolean {
  return role !== undefined && EVALUATION_RUN_ROLES.has(role);
}

/**
 * Start Run / Compare inputs (Phase 23 Chunk 3). `EvaluationRunCreate` and
 * `EvaluationRunCompare` are both already correctly generated (the request
 * write shape matches the request body exactly), so these are simple aliases
 * rather than re-typed — unlike the dataset/case create inputs above, there
 * is no schema gap on the request side here.
 */
export interface StartEvaluationRunInput {
  dataset_id: string;
  agent_version_id: string;
  threshold_config?: unknown;
}

export interface EvaluationRunCompareInput {
  baseline_run_id: string;
  candidate_run_id: string;
}

/**
 * Hand-typed from the real backend return shape (evaluations/services.py
 * `compare_evaluation_runs`/`_run_metrics`/`_evaluate_thresholds`) — see
 * api.ts schema gap 7: the generated 200 response has no body type at all.
 * Every field here is a value the backend actually computes and returns;
 * nothing here is invented — no comparison "score" or "improvement"
 * percentage beyond the real `deltas` (candidate metric minus baseline
 * metric, rounded server-side) and `regressions`/`passed` the backend itself
 * derives from the run's own `threshold_config`.
 */
export interface EvaluationRunMetrics {
  pass_rate: number;
  forbidden_tool_violations: number;
  approval_violations: number;
  handoff_rate: number;
  [key: string]: number;
}

export interface EvaluationRunCompareThresholdResult {
  threshold: unknown;
  passed: boolean;
}

export interface EvaluationRunCompareResult {
  baseline_run_id: string;
  candidate_run_id: string;
  case_count: number;
  baseline_metrics: EvaluationRunMetrics;
  candidate_metrics: EvaluationRunMetrics;
  deltas: Record<string, number>;
  thresholds: Record<string, EvaluationRunCompareThresholdResult>;
  regressions: string[];
  passed: boolean;
}

/**
 * Minimal agent-version-picker option types (Phase 23 Chunk 3 — see api.ts
 * `fetchAgentDefinitionOptions`/`fetchAgentVersionOptions`). Deliberately not
 * the full generated `AgentDefinition`/`AgentVersion` shapes — only the
 * fields the "Start Run" picker actually renders.
 */
export interface AgentDefinitionOption {
  id: string;
  name: string;
  status?: string;
}

export interface AgentVersionOption {
  id: string;
  version: number;
  status: string;
}
