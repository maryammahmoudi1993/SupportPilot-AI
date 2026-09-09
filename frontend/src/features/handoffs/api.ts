/**
 * Typed API boundary for the handoffs domain — read-only this chunk (master
 * prompt Part G §31): `assign`/`resolve` are real backend endpoints
 * (tickets/urls.py `handoff-assign`/`handoff-resolve`, manager-role-gated)
 * but are not implemented here — see frontend/README.md.
 *
 * Schema gap (Category A — the same global filter-backend inference gap
 * documented for every other domain): the generated
 * `api_v1_workspaces_handoffs_list` operation only types `ordering`, `page`,
 * `page_size`, `search`. The REAL, backend-tested filters (tickets/
 * selectors.py `handoff_list_for_workspace`) are `status` and
 * `conversation` — notably **not** `agent_run`, which is why AgentRun
 * detail (Chunk 1/2) never embeds a "related handoff" section: there is no
 * real, filtered way to ask "handoffs for this run" (master prompt Part H
 * §34, "no relationship inference").
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  HandoffListParams,
  HumanHandoff,
  PaginatedHumanHandoffList,
} from "@/features/handoffs/types";
import type { paths } from "@/types/api";

type GeneratedHandoffListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/handoffs/"]["get"]["parameters"]["query"]
>;

type HandoffListQuery = Omit<GeneratedHandoffListQuery, "ordering" | "search"> & {
  status?: string;
  conversation?: string;
};

function toHandoffListQuery(params: HandoffListParams): HandoffListQuery {
  const query: HandoffListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  return query;
}

export function fetchHandoffList(
  workspaceId: string,
  params: HandoffListParams,
  signal?: AbortSignal,
): Promise<PaginatedHumanHandoffList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/handoffs/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toHandoffListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchHandoffsForConversation(
  workspaceId: string,
  conversationId: string,
  signal?: AbortSignal,
): Promise<PaginatedHumanHandoffList> {
  const query: HandoffListQuery = { conversation: conversationId };
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/handoffs/", {
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

export function fetchHandoffDetail(
  workspaceId: string,
  handoffId: string,
  signal?: AbortSignal,
): Promise<HumanHandoff> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/handoffs/{handoff_id}/", {
          params: { path: { workspace_id: workspaceId, handoff_id: handoffId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}
