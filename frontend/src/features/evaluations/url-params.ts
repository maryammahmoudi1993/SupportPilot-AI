/**
 * Shareable/restorable URL query-string state for the evaluation run list and
 * a run's results panel — same pattern and untrusted-input posture as
 * features/agent-runs/url-params.ts. The results panel lives on the run
 * detail route, which owns no other query-string state in Chunk 1, so its
 * params use a distinct `resultsPage`/`passed` naming pair to stay
 * unambiguous if a future chunk adds detail-page state of its own.
 */
import type {
  EvaluationResultListParams,
  EvaluationResultPassedFilter,
  EvaluationRunListParams,
  EvaluationRunStatusFilter,
} from "@/features/evaluations/types";
import {
  DEFAULT_EVALUATION_RESULT_LIST_PARAMS,
  DEFAULT_EVALUATION_RUN_LIST_PARAMS,
} from "@/features/evaluations/types";

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
