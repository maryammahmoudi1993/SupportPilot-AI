/**
 * Typed API boundary for the evaluations domain.
 *
 * Every call goes through `apiClient` + `unwrap(withRequestTimeout(...))` —
 * the same pattern as every other domain — no raw `fetch`.
 *
 * Schema gap (Category A — a typing deficiency, not a missing capability):
 * the generated `api_v1_workspaces_evaluations_runs_list` and
 * `api_v1_workspaces_evaluations_runs_results_list` operations only type
 * `ordering`, `page`, `page_size`, `search` as query parameters — the same
 * global filter-backend inference gap documented for every prior domain
 * (agent-runs, tool-executions, tickets, ...). The REAL, backend-tested
 * filters (evaluations/views.py `EvaluationRunListCreateView.get_queryset`,
 * `EvaluationResultListView.get_queryset`; evaluations/selectors.py
 * `run_list_for_workspace`, `result_list_for_run`) are `status`/`dataset_id`
 * for runs and `status`/`passed` for results — none of which
 * drf-spectacular can see because both views read them directly from
 * `request.query_params` rather than a filter-backend attribute.
 * `EvaluationRunListQuery`/`EvaluationResultListQuery` below narrow this
 * explicitly. `ordering`/`search` are dead parameters exactly as elsewhere:
 * the backend orders both lists itself (`-created_at, -id` for runs;
 * `case_snapshot__sequence, id` for results) and never reads either — never
 * sent.
 *
 * `dataset_id` is a real backend run-list filter but is not surfaced as a
 * Chunk 1 list-page control — no dataset browse/picker UI exists yet
 * (Evaluation Dataset/Case management is out of Chunk 1 scope, same
 * reasoning as agent-runs' `agent_id`) — so it is typed here for
 * completeness but unused until a real caller needs it. Same for results'
 * `status` filter: `passed` is the one Chunk 1 exposes as a control (the
 * server-authoritative pass/fail outcome is the higher-value real signal for
 * a read-only foundation); `status` is typed but unused for the same reason.
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  CreateEvaluationCaseInput,
  CreateEvaluationDatasetInput,
  EvaluationCase,
  EvaluationCaseListParams,
  EvaluationDataset,
  EvaluationDatasetListParams,
  EvaluationResult,
  EvaluationResultListParams,
  EvaluationRun,
  EvaluationRunListParams,
  PaginatedEvaluationCaseList,
  PaginatedEvaluationDatasetList,
  PaginatedEvaluationResultList,
  PaginatedEvaluationRunList,
  UpdateEvaluationCaseInput,
  UpdateEvaluationDatasetInput,
} from "@/features/evaluations/types";
import type { paths } from "@/types/api";

type GeneratedEvaluationRunListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/evaluations/runs/"]["get"]["parameters"]["query"]
>;
type EvaluationRunListQuery = Omit<GeneratedEvaluationRunListQuery, "ordering" | "search"> & {
  status?: string;
  dataset_id?: string;
};

type GeneratedEvaluationResultListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/evaluations/runs/{run_id}/results/"]["get"]["parameters"]["query"]
>;
type EvaluationResultListQuery = Omit<
  GeneratedEvaluationResultListQuery,
  "ordering" | "search"
> & {
  status?: string;
  passed?: boolean;
};

function toRunListQuery(params: EvaluationRunListParams): EvaluationRunListQuery {
  const query: EvaluationRunListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  return query;
}

function toResultListQuery(params: EvaluationResultListParams): EvaluationResultListQuery {
  const query: EvaluationResultListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.passed !== "all") {
    query.passed = params.passed === "passed";
  }
  return query;
}

export function fetchEvaluationRunList(
  workspaceId: string,
  params: EvaluationRunListParams,
  signal?: AbortSignal,
): Promise<PaginatedEvaluationRunList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/evaluations/runs/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toRunListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchEvaluationRunDetail(
  workspaceId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<EvaluationRun> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/evaluations/runs/{run_id}/", {
          params: { path: { workspace_id: workspaceId, run_id: runId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchEvaluationResultList(
  workspaceId: string,
  runId: string,
  params: EvaluationResultListParams,
  signal?: AbortSignal,
): Promise<PaginatedEvaluationResultList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/evaluations/runs/{run_id}/results/", {
          params: {
            path: { workspace_id: workspaceId, run_id: runId },
            query: toResultListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchEvaluationResultDetail(
  workspaceId: string,
  runId: string,
  resultId: string,
  signal?: AbortSignal,
): Promise<EvaluationResult> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/evaluations/runs/{run_id}/results/{result_id}/",
          {
            params: {
              path: { workspace_id: workspaceId, run_id: runId, result_id: resultId },
            },
            signal: requestSignal,
          },
        ),
      undefined,
      signal,
    ),
  );
}

/**
 * Dataset/Case API (Phase 23 Chunk 2). Real filters (see selectors.py
 * `dataset_list_for_workspace`/`case_list_for_dataset`) are `status` for
 * both lists; `ordering`/`search` are dead params, same gap as runs/results
 * above — never sent.
 */
type GeneratedEvaluationDatasetListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/evaluations/datasets/"]["get"]["parameters"]["query"]
>;
type EvaluationDatasetListQuery = Omit<
  GeneratedEvaluationDatasetListQuery,
  "ordering" | "search"
> & { status?: string };

type GeneratedEvaluationCaseListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/evaluations/datasets/{dataset_id}/cases/"]["get"]["parameters"]["query"]
>;
type EvaluationCaseListQuery = Omit<GeneratedEvaluationCaseListQuery, "ordering" | "search"> & {
  status?: string;
};

function toDatasetListQuery(params: EvaluationDatasetListParams): EvaluationDatasetListQuery {
  const query: EvaluationDatasetListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  return query;
}

function toCaseListQuery(params: EvaluationCaseListParams): EvaluationCaseListQuery {
  const query: EvaluationCaseListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  return query;
}

export function fetchEvaluationDatasetList(
  workspaceId: string,
  params: EvaluationDatasetListParams,
  signal?: AbortSignal,
): Promise<PaginatedEvaluationDatasetList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/evaluations/datasets/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toDatasetListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchEvaluationDatasetDetail(
  workspaceId: string,
  datasetId: string,
  signal?: AbortSignal,
): Promise<EvaluationDataset> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/evaluations/datasets/{dataset_id}/", {
          params: { path: { workspace_id: workspaceId, dataset_id: datasetId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

/**
 * Return type declared explicitly as the real `EvaluationDataset` —
 * see types.ts schema gap 5: the generated 201 response is mistyped as the
 * request write shape.
 */
export function createEvaluationDataset(
  workspaceId: string,
  input: CreateEvaluationDatasetInput,
): Promise<EvaluationDataset> {
  return unwrap(
    withRequestTimeout((requestSignal) =>
      apiClient.POST("/api/v1/workspaces/{workspace_id}/evaluations/datasets/", {
        params: { path: { workspace_id: workspaceId } },
        body: input,
        signal: requestSignal,
      }),
    ),
  ) as Promise<EvaluationDataset>;
}

export function updateEvaluationDataset(
  workspaceId: string,
  datasetId: string,
  input: UpdateEvaluationDatasetInput,
): Promise<EvaluationDataset> {
  return unwrap(
    withRequestTimeout((requestSignal) =>
      apiClient.PATCH("/api/v1/workspaces/{workspace_id}/evaluations/datasets/{dataset_id}/", {
        params: { path: { workspace_id: workspaceId, dataset_id: datasetId } },
        body: input,
        signal: requestSignal,
      }),
    ),
  );
}

export function fetchEvaluationCaseList(
  workspaceId: string,
  datasetId: string,
  params: EvaluationCaseListParams,
  signal?: AbortSignal,
): Promise<PaginatedEvaluationCaseList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET(
          "/api/v1/workspaces/{workspace_id}/evaluations/datasets/{dataset_id}/cases/",
          {
            params: {
              path: { workspace_id: workspaceId, dataset_id: datasetId },
              query: toCaseListQuery(params),
            },
            signal: requestSignal,
          },
        ),
      undefined,
      signal,
    ),
  );
}

/** Return type declared explicitly as the real `EvaluationCase` — see types.ts schema gap 5. */
export function createEvaluationCase(
  workspaceId: string,
  datasetId: string,
  input: CreateEvaluationCaseInput,
): Promise<EvaluationCase> {
  return unwrap(
    withRequestTimeout((requestSignal) =>
      apiClient.POST(
        "/api/v1/workspaces/{workspace_id}/evaluations/datasets/{dataset_id}/cases/",
        {
          params: { path: { workspace_id: workspaceId, dataset_id: datasetId } },
          body: input,
          signal: requestSignal,
        },
      ),
    ),
  ) as Promise<EvaluationCase>;
}

export function updateEvaluationCase(
  workspaceId: string,
  datasetId: string,
  caseId: string,
  input: UpdateEvaluationCaseInput,
): Promise<EvaluationCase> {
  return unwrap(
    withRequestTimeout((requestSignal) =>
      apiClient.PATCH(
        "/api/v1/workspaces/{workspace_id}/evaluations/datasets/{dataset_id}/cases/{case_id}/",
        {
          params: {
            path: { workspace_id: workspaceId, dataset_id: datasetId, case_id: caseId },
          },
          body: input,
          signal: requestSignal,
        },
      ),
    ),
  );
}
