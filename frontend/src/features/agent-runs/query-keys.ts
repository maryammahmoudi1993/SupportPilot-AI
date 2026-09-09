/**
 * Typed, workspace-scoped query key factory for the agent-runs domain — same
 * policy as tickets/customers/conversations (see
 * features/tickets/query-keys.ts): every key embeds the workspace ID as its
 * second segment, so a workspace switch produces a disjoint cache entry,
 * never a stale one another workspace could render.
 */
import type { AgentRunListParams } from "@/features/agent-runs/types";

export const agentRunKeys = {
  all: (workspaceId: string) => ["workspaces", workspaceId, "agent-runs"] as const,
  lists: (workspaceId: string) => [...agentRunKeys.all(workspaceId), "list"] as const,
  list: (workspaceId: string, params: AgentRunListParams) =>
    [...agentRunKeys.lists(workspaceId), params] as const,
  details: (workspaceId: string) => [...agentRunKeys.all(workspaceId), "detail"] as const,
  detail: (workspaceId: string, runId: string) =>
    [...agentRunKeys.details(workspaceId), runId] as const,
  steps: (workspaceId: string, runId: string) =>
    [...agentRunKeys.detail(workspaceId, runId), "steps"] as const,
};
