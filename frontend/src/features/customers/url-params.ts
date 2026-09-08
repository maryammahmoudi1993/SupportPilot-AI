/**
 * Shareable/restorable URL query-string state for the customers list.
 *
 * `URLSearchParams` values are untrusted input (a bookmarked/shared/hand-
 * edited link) — every field is validated here, with a safe fallback
 * instead of forwarding whatever the user typed straight to the API.
 */
import type { CustomerListParams, CustomerStatusFilter } from "@/features/customers/types";
import { DEFAULT_CUSTOMER_LIST_PARAMS } from "@/features/customers/types";

const MAX_SEARCH_LENGTH = 200;

function parsePage(raw: string | null): number {
  if (!raw || !/^[1-9]\d*$/.test(raw)) {
    return DEFAULT_CUSTOMER_LIST_PARAMS.page;
  }
  const page = Number(raw);
  return Number.isSafeInteger(page) ? page : DEFAULT_CUSTOMER_LIST_PARAMS.page;
}

function parseStatus(raw: string | null): CustomerStatusFilter {
  return raw === "active" || raw === "inactive" ? raw : "all";
}

export function parseCustomerListParams(searchParams: URLSearchParams): CustomerListParams {
  return {
    page: parsePage(searchParams.get("page")),
    search: (searchParams.get("search") ?? "").slice(0, MAX_SEARCH_LENGTH),
    status: parseStatus(searchParams.get("status")),
  };
}

/** Inverse of `parseCustomerListParams` — omits defaulted fields so the URL stays clean. */
export function buildCustomerListQueryString(params: CustomerListParams): string {
  const search = new URLSearchParams();
  if (params.page > 1) {
    search.set("page", String(params.page));
  }
  const trimmedSearch = params.search.trim();
  if (trimmedSearch.length > 0) {
    search.set("search", trimmedSearch);
  }
  if (params.status !== "all") {
    search.set("status", params.status);
  }
  const query = search.toString();
  return query.length > 0 ? `?${query}` : "";
}
