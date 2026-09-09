/**
 * Shareable/restorable URL query-string state for the handoff list — same
 * pattern and untrusted-input posture as features/agent-runs/url-params.ts.
 */
import type { HandoffListParams, HandoffStatusFilter } from "@/features/handoffs/types";
import { DEFAULT_HANDOFF_LIST_PARAMS } from "@/features/handoffs/types";

const VALID_STATUSES: readonly string[] = ["pending", "assigned", "resolved", "cancelled"];

function parsePage(raw: string | null): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return DEFAULT_HANDOFF_LIST_PARAMS.page;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : DEFAULT_HANDOFF_LIST_PARAMS.page;
}

function parseStatus(raw: string | null): HandoffStatusFilter {
  return raw && VALID_STATUSES.includes(raw) ? (raw as HandoffStatusFilter) : "all";
}

export function parseHandoffListParams(searchParams: URLSearchParams): HandoffListParams {
  return {
    page: parsePage(searchParams.get("page")),
    status: parseStatus(searchParams.get("status")),
  };
}

export function buildHandoffListQueryString(params: HandoffListParams): string {
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
