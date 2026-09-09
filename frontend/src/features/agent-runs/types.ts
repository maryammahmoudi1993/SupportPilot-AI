/**
 * Agent Run domain types (Phase 20 Chunk 1: Agent Runs + Run Detail +
 * Lifecycle Visibility).
 *
 * Re-exported from the generated OpenAPI schema — `AgentRun` and `AgentStep`
 * are both fully server-derived (`read_only_fields = fields`, see
 * backend/agents/serializers.py), so no write-shape narrowing is needed
 * beyond the list-filter gap documented in api.ts.
 */
import type { components } from "@/types/api";

export type AgentRun = components["schemas"]["AgentRun"];
export type AgentStep = components["schemas"]["AgentStep"];
export type PaginatedAgentRunList = components["schemas"]["PaginatedAgentRunList"];

export type AgentRunStatusValue = components["schemas"]["AgentRunStatusEnum"];
export type AgentRunTriggerValue = components["schemas"]["AgentRunTriggerEnum"];
export type AgentStepTypeValue = components["schemas"]["AgentStepTypeEnum"];
export type AgentStepStatusValue = components["schemas"]["AgentStepStatusEnum"];

/** `"all"` omits the corresponding filter from the request entirely. */
export type AgentRunStatusFilter = "all" | AgentRunStatusValue;

/**
 * The backend's real terminal-status set (agents/models.py
 * `AGENT_RUN_TERMINAL_STATUSES`) — mirrored here rather than imported
 * (frontend/backend are separate deployables). A run in any other status is
 * non-terminal and eligible for polling (see queries.ts).
 */
export const AGENT_RUN_TERMINAL_STATUSES: ReadonlySet<AgentRunStatusValue> = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "budget_exceeded",
  "handed_off",
]);

export function isTerminalRunStatus(status: AgentRunStatusValue): boolean {
  return AGENT_RUN_TERMINAL_STATUSES.has(status);
}

export interface AgentRunListParams {
  page: number;
  status: AgentRunStatusFilter;
}

export const DEFAULT_AGENT_RUN_LIST_PARAMS: AgentRunListParams = {
  page: 1,
  status: "all",
};
