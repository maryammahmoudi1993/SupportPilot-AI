/**
 * Typed API boundary for the tool-executions domain.
 *
 * Every call goes through `apiClient` + `unwrap(withRequestTimeout(...))` —
 * the same pattern as every other domain — no raw `fetch`.
 *
 * Schema gap (Category A — a typing deficiency, not a missing capability):
 * the generated `api_v1_workspaces_tools_tool_executions_list` operation
 * only types `ordering`, `page`, `page_size`, `search` as query parameters —
 * the same global filter-backend inference gap documented for every prior
 * domain. The REAL, backend-tested filters (tools/views.py
 * `ToolExecutionListView.get_queryset`, tools/selectors.py
 * `tool_execution_list_for_workspace`) are `status` and `agent_run_id`.
 * `ToolExecutionListQuery` below narrows this explicitly. `ordering`/
 * `search` are dead parameters exactly as elsewhere: the backend orders
 * executions itself (`-created_at, -id`) and never reads either.
 *
 * `agent_run_id` is the only filter this chunk actually sends — one Agent
 * Run's tool executions, always fetched as a single, bounded page. An
 * AgentVersion's `max_tool_calls` is server-capped at 20
 * (agents/serializers.py `AgentVersionWriteSerializer`), well under the
 * default page size (50), so a single unpaginated fetch per run is provably
 * complete, never a silently-truncated first page.
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  PaginatedToolDefinitionList,
  PaginatedToolExecutionList,
} from "@/features/tool-executions/types";
import type { paths } from "@/types/api";

type GeneratedToolExecutionListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/tools/tool-executions/"]["get"]["parameters"]["query"]
>;

type ToolExecutionListQuery = Omit<GeneratedToolExecutionListQuery, "ordering" | "search"> & {
  agent_run_id?: string;
};

export function fetchToolExecutionsForRun(
  workspaceId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<PaginatedToolExecutionList> {
  const query: ToolExecutionListQuery = { agent_run_id: runId };
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/tools/tool-executions/", {
          params: {
            path: { workspace_id: workspaceId },
            query,
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

/**
 * The tool catalog (`GET /tools/`) is code-owned, workspace-independent
 * metadata (tools/views.py `ToolCatalogListView` — same rows for every
 * workspace) — fetched once per Agent Run detail view, not per tool
 * execution, purely to attach each execution's real `risk_level`/
 * `side_effect_type` (present on `ToolDefinition`, absent from
 * `ToolExecution` itself). Currently 3 real demo tools, far under the
 * default page size (50); a single unpaginated fetch is complete today, and
 * this is the one bounded, cacheable request that avoids a per-row N+1 if
 * the catalog ever grows within one page.
 */
export function fetchToolCatalog(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<PaginatedToolDefinitionList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/tools/", {
          params: { path: { workspace_id: workspaceId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}
