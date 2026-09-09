/**
 * Shareable/restorable URL query-string state for the approval list — same
 * pattern and untrusted-input posture as features/agent-runs/url-params.ts.
 * Defaults to `status=pending` (an operator queue is most useful showing
 * what still needs a decision) rather than `all` — the default is simply
 * never written to the query string, exactly like every other domain's
 * default filter.
 */
import type { ApprovalListParams, ApprovalStatusFilter } from "@/features/approvals/types";
import { DEFAULT_APPROVAL_LIST_PARAMS } from "@/features/approvals/types";

const VALID_STATUSES: readonly string[] = [
  "pending",
  "approved",
  "rejected",
  "expired",
  "cancelled",
];

function parsePage(raw: string | null): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return DEFAULT_APPROVAL_LIST_PARAMS.page;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : DEFAULT_APPROVAL_LIST_PARAMS.page;
}

function parseStatus(raw: string | null): ApprovalStatusFilter {
  return raw && VALID_STATUSES.includes(raw) ? (raw as ApprovalStatusFilter) : "all";
}

export function parseApprovalListParams(searchParams: URLSearchParams): ApprovalListParams {
  const hasStatusParam = searchParams.has("status");
  return {
    page: parsePage(searchParams.get("page")),
    status: hasStatusParam
      ? parseStatus(searchParams.get("status"))
      : DEFAULT_APPROVAL_LIST_PARAMS.status,
  };
}

export function buildApprovalListQueryString(params: ApprovalListParams): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  if (params.status !== DEFAULT_APPROVAL_LIST_PARAMS.status) {
    search.set("status", params.status);
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}
