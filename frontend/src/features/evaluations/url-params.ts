/**
 * Shareable/restorable URL query-string state for the evaluation run list and
 * a run's results panel — same pattern and untrusted-input posture as
 * features/agent-runs/url-params.ts. The results panel lives on the run
 * detail route, which owns no other query-string state in Chunk 1, so its
 * params use a distinct `resultsPage`/`passed` naming pair to stay
 * unambiguous if a future chunk adds detail-page state of its own.
 */
import type {
  EvaluationCaseListParams,
  EvaluationCaseStatusFilter,
  EvaluationDatasetListParams,
  EvaluationDatasetStatusFilter,
  EvaluationResultListParams,
  EvaluationResultPassedFilter,
  EvaluationRunListParams,
  EvaluationRunStatusFilter,
} from "@/features/evaluations/types";
import {
  DEFAULT_EVALUATION_CASE_LIST_PARAMS,
  DEFAULT_EVALUATION_DATASET_LIST_PARAMS,
  DEFAULT_EVALUATION_RESULT_LIST_PARAMS,
  DEFAULT_EVALUATION_RUN_LIST_PARAMS,
} from "@/features/evaluations/types";

/** The `/app/evaluations` route's own tab state — same pattern as `KnowledgeTab`. */
export type EvaluationTab = "runs" | "datasets";

export function parseEvaluationTab(searchParams: URLSearchParams): EvaluationTab {
  return searchParams.get("tab") === "datasets" ? "datasets" : "runs";
}

const VALID_RUN_STATUSES: readonly string[] = [
  "pending",
  "running",
  "succeeded",
  "partial",
  "failed",
  "cancelled",
];

const VALID_PASSED_FILTERS: readonly string[] = ["passed", "failed"];

function parsePage(raw: string | null, fallback: number): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return fallback;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : fallback;
}

function parseRunStatus(raw: string | null): EvaluationRunStatusFilter {
  return raw && VALID_RUN_STATUSES.includes(raw) ? (raw as EvaluationRunStatusFilter) : "all";
}

export function parseEvaluationRunListParams(
  searchParams: URLSearchParams,
): EvaluationRunListParams {
  return {
    page: parsePage(searchParams.get("page"), DEFAULT_EVALUATION_RUN_LIST_PARAMS.page),
    status: parseRunStatus(searchParams.get("status")),
  };
}

export function buildEvaluationRunListQueryString(params: EvaluationRunListParams): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  if (params.status !== "all") {
    search.set("status", params.status);
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}

function parsePassedFilter(raw: string | null): EvaluationResultPassedFilter {
  return raw && VALID_PASSED_FILTERS.includes(raw) ? (raw as EvaluationResultPassedFilter) : "all";
}

export function parseEvaluationResultListParams(
  searchParams: URLSearchParams,
): EvaluationResultListParams {
  return {
    page: parsePage(searchParams.get("resultsPage"), DEFAULT_EVALUATION_RESULT_LIST_PARAMS.page),
    passed: parsePassedFilter(searchParams.get("passed")),
  };
}

export function buildEvaluationResultListQueryString(params: EvaluationResultListParams): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("resultsPage", String(params.page));
  }
  if (params.passed !== "all") {
    search.set("passed", params.passed);
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}

const VALID_DATASET_STATUSES: readonly string[] = ["draft", "active", "archived"];
const VALID_CASE_STATUSES: readonly string[] = ["active", "disabled"];

function parseDatasetStatus(raw: string | null): EvaluationDatasetStatusFilter {
  return raw && VALID_DATASET_STATUSES.includes(raw)
    ? (raw as EvaluationDatasetStatusFilter)
    : "all";
}

/** `/app/evaluations?tab=datasets` — reuses `page`/`status` like the Runs
 * tab (same pattern as Knowledge's Documents/Sources tabs: only one tab's
 * params are meaningful at a time, so switching tabs naturally resets them). */
export function parseEvaluationDatasetListParams(
  searchParams: URLSearchParams,
): EvaluationDatasetListParams {
  return {
    page: parsePage(searchParams.get("page"), DEFAULT_EVALUATION_DATASET_LIST_PARAMS.page),
    status: parseDatasetStatus(searchParams.get("status")),
  };
}

export function buildEvaluationDatasetListQueryString(
  params: EvaluationDatasetListParams,
): string {
  const search = new URLSearchParams();
  search.set("tab", "datasets");
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  if (params.status !== "all") {
    search.set("status", params.status);
  }
  return `?${search.toString()}`;
}

function parseCaseStatus(raw: string | null): EvaluationCaseStatusFilter {
  return raw && VALID_CASE_STATUSES.includes(raw) ? (raw as EvaluationCaseStatusFilter) : "all";
}

/** Dataset detail route's own case-list state — distinct `casePage`/`caseStatus`
 * names, same reasoning as the run detail route's `resultsPage`/`passed`. */
export function parseEvaluationCaseListParams(
  searchParams: URLSearchParams,
): EvaluationCaseListParams {
  return {
    page: parsePage(searchParams.get("casePage"), DEFAULT_EVALUATION_CASE_LIST_PARAMS.page),
    status: parseCaseStatus(searchParams.get("caseStatus")),
  };
}

export function buildEvaluationCaseListQueryString(params: EvaluationCaseListParams): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("casePage", String(params.page));
  }
  if (params.status !== "all") {
    search.set("caseStatus", params.status);
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}
