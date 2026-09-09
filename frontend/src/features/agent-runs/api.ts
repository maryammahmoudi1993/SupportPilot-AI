/**
 * Typed API boundary for the agent-runs domain.
 *
 * Every call goes through `apiClient` + `unwrap(withRequestTimeout(...))` —
 * the same pattern as features/tickets/api.ts and features/customers/api.ts
 * — no raw `fetch`.
 *
 * Schema gap (Category A — a typing deficiency, not a missing capability):
 *
 * The generated `api_v1_workspaces_agent_runs_list` operation only types
 * `ordering`, `page`, `page_size`, `search` as query parameters — the same
 * global filter-backend inference gap already documented for
 * tickets/customers/conversations. The REAL, backend-tested filters
 * (agents/views.py `AgentRunListCreateView.get_queryset`, agents/selectors.py
 * `agent_run_list_for_workspace`) are `status` and `agent_id`, neither of
 * which drf-spectacular can see because the view reads them directly from
 * `request.query_params` rather than a filter-backend attribute.
 * `AgentRunListQuery` below narrows this explicitly. `ordering` and `search`
 * are dead parameters exactly as for tickets: the backend orders runs itself
 * (`-created_at, -id`) and never reads either. Never sent.
 *
 * `agent_id` (filter by originating AgentDefinition) is a real backend filter
 * but is not surfaced as a Chunk 1 list-page control — no agent picker UI
 * exists yet (Agent Definition management is out of Phase 20 scope) — so it
 * is typed here for completeness but unused until a real caller needs it.
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  AgentRun,
  AgentRunListParams,
  AgentStep,
  PaginatedAgentRunList,
} from "@/features/agent-runs/types";
import type { paths } from "@/types/api";

type GeneratedAgentRunListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/agent-runs/"]["get"]["parameters"]["query"]
>;

/** See the module doc comment: `status`/`agent_id` are real but absent from the generated schema. */
type AgentRunListQuery = Omit<GeneratedAgentRunListQuery, "ordering" | "search"> & {
  status?: string;
  agent_id?: string;
};

function toAgentRunListQuery(params: AgentRunListParams): AgentRunListQuery {
  const query: AgentRunListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  return query;
}

export function fetchAgentRunList(
  workspaceId: string,
  params: AgentRunListParams,
  signal?: AbortSignal,
): Promise<PaginatedAgentRunList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/agent-runs/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toAgentRunListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchAgentRunDetail(
  workspaceId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<AgentRun> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/agent-runs/{run_id}/", {
          params: { path: { workspace_id: workspaceId, run_id: runId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchAgentRunSteps(
  workspaceId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<AgentStep[]> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/agent-runs/{run_id}/steps/", {
          params: { path: { workspace_id: workspaceId, run_id: runId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}
