/**
 * React Query hooks for the customers domain. See query-keys.ts for the
 * workspace-scoped key policy and lib/query/query-client.ts for the shared
 * retry policy.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchCustomerDetail, fetchCustomerList } from "@/features/customers/api";
import { customerKeys } from "@/features/customers/query-keys";
import type { Customer, CustomerListParams, PaginatedCustomerList } from "@/features/customers/types";
import type { ApiError } from "@/lib/api/errors";

/** Stand-in workspace segment for a disabled query — never actually requested (`enabled: false`). */
const NO_WORKSPACE = "no-workspace";

function isSameWorkspaceQuery(queryKey: readonly unknown[], workspaceId: string): boolean {
  return queryKey[1] === workspaceId;
}

export function useCustomerListQuery(workspaceId: string | null, params: CustomerListParams) {
  return useQuery<PaginatedCustomerList, ApiError>({
    queryKey: customerKeys.list(workspaceId ?? NO_WORKSPACE, params),
    queryFn: ({ signal }) => fetchCustomerList(workspaceId as string, params, signal),
    enabled: workspaceId !== null,
    // Keep the previous page's rows on screen while the next page/filter
    // loads — but ONLY when the previous successful query was for the SAME
    // workspace. Reusing another workspace's placeholder data here would be
    // exactly the cross-tenant flash the workspace-isolation requirement
    // forbids (see query-keys.ts and Chunk 1's workspace-isolation tests).
    placeholderData: (previousData: PaginatedCustomerList | undefined, previousQuery) => {
      if (workspaceId === null || !previousQuery) {
        return undefined;
      }
      return isSameWorkspaceQuery(previousQuery.queryKey, workspaceId) ? previousData : undefined;
    },
  });
}

export function useCustomerDetailQuery(workspaceId: string | null, customerId: string | null) {
  return useQuery<Customer, ApiError>({
    queryKey: customerKeys.detail(workspaceId ?? NO_WORKSPACE, customerId ?? ""),
    queryFn: ({ signal }) => fetchCustomerDetail(workspaceId as string, customerId as string, signal),
    enabled: workspaceId !== null && customerId !== null,
  });
}
