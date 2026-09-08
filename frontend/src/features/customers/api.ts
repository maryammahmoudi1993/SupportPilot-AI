/**
 * Typed API boundary for the customers domain.
 *
 * Every call goes through `apiClient` (generated-type-checked against the
 * real backend OpenAPI schema) and `requestWithTimeout` (bounded, abortable
 * — see lib/api/request.ts) — no raw `fetch` anywhere in this module.
 *
 * Schema gap (Category A — typing deficiency, not a missing capability):
 * the generated `api_v1_workspaces_customers_list` operation only types
 * `ordering`, `page`, `page_size`, and `search` as query parameters.
 * `is_active` is a real, backend-tested filter (customers/selectors.py
 * `customer_list_for_workspace`, customers/views.py `_as_bool`) that
 * `drf-spectacular` simply can't see, because the view reads it directly
 * from `request.query_params` instead of declaring it through a filter
 * backend attribute. `CustomerListQuery` narrows this explicitly (no `any`,
 * no `ts-ignore`) rather than inventing a filter that doesn't exist —
 * see frontend/README.md, "Customer API contract gaps".
 *
 * `ordering` is deliberately never sent: it appears in the generated schema
 * only because `OrderingFilter` is in the project's global
 * `DEFAULT_FILTER_BACKENDS`, but the customers view sets no `ordering_fields`,
 * so the backend silently ignores the parameter — sending it would be a
 * dead control (see backend/customers/views.py, backend/customers/tests/test_views.py).
 */
import { apiClient } from "@/lib/api/client";
import { unwrap, withRequestTimeout } from "@/lib/api/request";
import type { CustomerListParams, Customer, PaginatedCustomerList } from "@/features/customers/types";
import type { paths } from "@/types/api";

type GeneratedCustomerListQuery = NonNullable<
  paths["/api/v1/workspaces/{workspace_id}/customers/"]["get"]["parameters"]["query"]
>;

/** See the module doc comment: `is_active` is real but absent from the generated schema. */
type CustomerListQuery = Omit<GeneratedCustomerListQuery, "ordering"> & {
  is_active?: boolean;
};

function toRequestQuery(params: CustomerListParams): CustomerListQuery {
  const query: CustomerListQuery = {};
  if (params.page > 1) {
    query.page = params.page;
  }
  const trimmedSearch = params.search.trim();
  if (trimmedSearch.length > 0) {
    query.search = trimmedSearch;
  }
  if (params.status !== "all") {
    query.is_active = params.status === "active";
  }
  return query;
}

/**
 * `signal` is React Query's own per-query abort signal (queryFn's `{ signal
 * }` argument) — chained as `withRequestTimeout`'s caller signal so a
 * cancelled/superseded query (e.g. a fast page/filter change) aborts the
 * in-flight request instead of leaving it to resolve into a stale result.
 */
export function fetchCustomerList(
  workspaceId: string,
  params: CustomerListParams,
  signal?: AbortSignal,
): Promise<PaginatedCustomerList> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/customers/", {
          params: {
            path: { workspace_id: workspaceId },
            query: toRequestQuery(params),
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}

export function fetchCustomerDetail(
  workspaceId: string,
  customerId: string,
  signal?: AbortSignal,
): Promise<Customer> {
  return unwrap(
    withRequestTimeout(
      (requestSignal) =>
        apiClient.GET("/api/v1/workspaces/{workspace_id}/customers/{customer_id}/", {
          params: {
            path: { workspace_id: workspaceId, customer_id: customerId },
          },
          signal: requestSignal,
        }),
      undefined,
      signal,
    ),
  );
}
