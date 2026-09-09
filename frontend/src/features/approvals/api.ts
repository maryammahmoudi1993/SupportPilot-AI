/**
 * Typed API boundary for the approvals domain.
 *
 * Every call goes through `apiClient` + `unwrap(withRequestTimeout(...))` —
 * the same pattern as every other domain — no raw `fetch`. Approve/Reject
 * are the first real mutations in this frontend (master prompt Part B):
 * `requestWithTimeout` (the `unwrap(withRequestTimeout(...))` composition,
 * see lib/api/request.ts) bounds them exactly like every read, and neither
 * carries any client-side automatic retry (React Query mutations never
 * retry by default — see queries.ts's `useDecideApprovalMutation`, which
 * doesn't set `retry` at all) — a blind retry of a decision mutation could
 * double-submit a real workflow transition (master prompt Part B §6).
 *
 * Schema gap (Category A — the same global filter-backend inference gap
 * documented for every prior domain): the generated
 * `api_v1_workspaces_approvals_list` operation only types `ordering`,
 * `page`, `page_size`, `search` as query parameters. The REAL, backend-
 * tested filters (approvals/views.py `ApprovalRequestListView.get_queryset`)
 * are `status`, `required_role`, and `tool_key` — this chunk's list UI only
 * surfaces `status` (a `required_role`/`tool_key` picker has no real backend
 * enum-list endpoint to populate it from, and isn't part of this chunk's
 * scope). `ordering`/`search` are dead parameters exactly as elsewhere: the
 * backend orders requests itself (`created_at, id` — pending-first, oldest
 * first) and never reads either.
 */
import { apiClient } from "@/lib/api/client";
import { requestWithTimeout, unwrap, withRequestTimeout } from "@/lib/api/request";
import type {
  ApprovalListParams,
  ApprovalRequest,
  PaginatedApprovalRequestList,
} from "@/features/approvals/types";
import type { paths } from "@/types/api";

type GeneratedApprovalListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/approvals/"]["get"]["parameters"]["query"]
>;

type ApprovalListQuery = Omit<GeneratedApprovalListQuery, "ordering" | "search"> & {
  status?: string;
};

function toApprovalListQuery(params: ApprovalListParams): ApprovalListQuery {
  const query: ApprovalListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  if (params.status !== "all") {
    query.status = params.status;
  }
  return query;
}

export function fetchApprovalList(
  workspaceId: string,
  params: ApprovalListParams,
  signal?: AbortSignal,
): Promise<PaginatedApprovalRequestList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/approvals/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toApprovalListQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchApprovalDetail(
  workspaceId: string,
  approvalId: string,
  signal?: AbortSignal,
): Promise<ApprovalRequest> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/approvals/{approval_id}/", {
          params: { path: { workspace_id: workspaceId, approval_id: approvalId } },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

/**
 * `comment` is the only body either endpoint accepts (approvals/serializers.py
 * `ApprovalDecisionInputSerializer`) — no reason is *required* server-side,
 * so this chunk never renders a required-comment form (master prompt §38).
 */
export function approveApproval(
  workspaceId: string,
  approvalId: string,
  comment?: string,
): Promise<ApprovalRequest> {
  return requestWithTimeout((signal) =>
    apiClient.POST("/api/v1/workspaces/{workspace_id}/approvals/{approval_id}/approve/", {
      params: { path: { workspace_id: workspaceId, approval_id: approvalId } },
      body: { comment: comment ?? "" },
      signal,
    }),
  );
}

export function rejectApproval(
  workspaceId: string,
  approvalId: string,
  comment?: string,
): Promise<ApprovalRequest> {
  return requestWithTimeout((signal) =>
    apiClient.POST("/api/v1/workspaces/{workspace_id}/approvals/{approval_id}/reject/", {
      params: { path: { workspace_id: workspaceId, approval_id: approvalId } },
      body: { comment: comment ?? "" },
      signal,
    }),
  );
}
