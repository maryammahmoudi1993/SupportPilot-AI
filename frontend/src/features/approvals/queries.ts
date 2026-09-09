/**
 * React Query hooks for the approvals domain.
 *
 * Polling strategy (master prompt Part E §22): only the approval *detail*
 * query polls, and only while the approval itself is `pending` — a pending
 * approval can be decided by another operator, or expire, entirely outside
 * this tab. The list view does not poll (master prompt §22, "avoid
 * duplicating AgentRun/Tool polling unnecessarily" — an operator watching
 * one pending request already gets that request's own 5s poll; a second,
 * independent poll of the whole queue underneath it would be a compounded
 * poll for no additional signal this chunk's UI surfaces). `useMutation`
 * mutations never set `retry` above 0 (TanStack Query v5's own default for
 * mutations is already 0 — asserted here, not just relied on, per master
 * prompt Part B §6: a blind retry of a decision call could double-submit a
 * real workflow transition).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveApproval,
  fetchApprovalDetail,
  fetchApprovalList,
  rejectApproval,
} from "@/features/approvals/api";
import { approvalKeys } from "@/features/approvals/query-keys";
import type { ApprovalListParams, ApprovalRequest } from "@/features/approvals/types";
import type { ApiError } from "@/lib/api/errors";

const NO_WORKSPACE = "no-workspace";
export const APPROVAL_POLL_INTERVAL_MS = 5000;

export function useApprovalListQuery(workspaceId: string | null, params: ApprovalListParams) {
  return useQuery<import("@/features/approvals/types").PaginatedApprovalRequestList, ApiError>({
    queryKey: approvalKeys.list(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchApprovalList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
  });
}

export function useApprovalDetailQuery(workspaceId: string | null, approvalId: string | null) {
  return useQuery<ApprovalRequest, ApiError>({
    queryKey: approvalKeys.detail(workspaceId ?? NO_WORKSPACE, approvalId ?? ""),
    queryFn: ({ signal }) =>
      fetchApprovalDetail(workspaceId as string, approvalId as string, signal),
    enabled: workspaceId !== null && approvalId !== null,
    refetchInterval: (query) =>
      query.state.data?.status === "pending" ? APPROVAL_POLL_INTERVAL_MS : false,
    refetchIntervalInBackground: false,
  });
}

/**
 * One mutation hook drives both Approve and Reject — `decide` is the only
 * thing that differs between the two endpoints (master prompt Part J §37-38:
 * the URL itself is the decision, mirroring the backend's own design).
 *
 * On success: the server's *returned* row (never an optimistic guess —
 * master prompt §40, §12) replaces the cached detail directly via
 * `setQueryData`, and the list cache is invalidated so a queue view
 * reflects the real new state on its next render. There is no related
 * AgentRun/ToolExecution cache to invalidate: `ApprovalRequest` exposes no
 * relation to either (see types.ts's doc comment) — nothing to invalidate
 * that this frontend can safely name.
 *
 * On error: nothing is written to the cache. The concurrency/already-
 * decided/expired/permission-denied cases (master prompt Part B §8-10, §19)
 * are handled by the caller refetching the detail query after the mutation
 * settles — see components/approval-detail-page.tsx — so the real,
 * server-confirmed state (not a guess) always wins.
 */
export function useDecideApprovalMutation(workspaceId: string, approvalId: string) {
  const queryClient = useQueryClient();
  return useMutation<
    ApprovalRequest,
    ApiError,
    { decision: "approve" | "reject"; comment?: string }
  >({
    retry: 0,
    mutationFn: ({ decision, comment }) =>
      decision === "approve"
        ? approveApproval(workspaceId, approvalId, comment)
        : rejectApproval(workspaceId, approvalId, comment),
    onSuccess: (approval) => {
      queryClient.setQueryData(approvalKeys.detail(workspaceId, approvalId), approval);
      void queryClient.invalidateQueries({ queryKey: approvalKeys.lists(workspaceId) });
    },
  });
}
