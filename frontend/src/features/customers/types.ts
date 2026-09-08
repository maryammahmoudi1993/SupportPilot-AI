/**
 * Customer domain types.
 *
 * `Customer`/`PaginatedCustomerList` are re-exported straight from the
 * generated OpenAPI schema (see scripts/generate-api-types.mjs) — no manual
 * DTO duplication for fields the schema already describes accurately.
 */
import type { components } from "@/types/api";

export type Customer = components["schemas"]["Customer"];
export type PaginatedCustomerList = components["schemas"]["PaginatedCustomerList"];

/** `"all"` omits the `is_active` filter entirely rather than sending it as a third enum value. */
export type CustomerStatusFilter = "all" | "active" | "inactive";

/** Request-shaped params sent to the customers list endpoint. */
export interface CustomerListParams {
  page: number;
  search: string;
  status: CustomerStatusFilter;
}

export const DEFAULT_CUSTOMER_LIST_PARAMS: CustomerListParams = {
  page: 1,
  search: "",
  status: "all",
};
