/**
 * Shareable/restorable URL query-string state for the agent-run list — same
 * pattern and untrusted-input posture as features/tickets/url-params.ts.
 */
import type { AgentRunListParams, AgentRunStatusFilter } from "@/features/agent-runs/types";
import { DEFAULT_AGENT_RUN_LIST_PARAMS } from "@/features/agent-runs/types";

const VALID_STATUSES: readonly string[] = [
  "pending",
  "running",
  "succeeded",
  "failed",
  "cancelled",
  "budget_exceeded",
  "waiting_for_approval",
  "handed_off",
];

function parsePage(raw: string | null): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return DEFAULT_AGENT_RUN_LIST_PARAMS.page;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : DEFAULT_AGENT_RUN_LIST_PARAMS.page;
}

function parseStatus(raw: string | null): AgentRunStatusFilter {
  return raw && VALID_STATUSES.includes(raw) ? (raw as AgentRunStatusFilter) : "all";
}

export function parseAgentRunListParams(searchParams: URLSearchParams): AgentRunListParams {
  return {
    page: parsePage(searchParams.get("page")),
    status: parseStatus(searchParams.get("status")),
  };
}

export function buildAgentRunListQueryString(params: AgentRunListParams): string {
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
