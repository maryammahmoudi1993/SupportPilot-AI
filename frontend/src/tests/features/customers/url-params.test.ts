import { describe, expect, it } from "vitest";

import { buildCustomerListQueryString, parseCustomerListParams } from "@/features/customers/url-params";

describe("parseCustomerListParams", () => {
  it("defaults to page 1, empty search, and 'all' status for an empty query string", () => {
    expect(parseCustomerListParams(new URLSearchParams())).toEqual({
      page: 1,
      search: "",
      status: "all",
    });
  });

  it("round-trips valid params", () => {
    const params = parseCustomerListParams(new URLSearchParams("page=3&search=jane&status=active"));
    expect(params).toEqual({ page: 3, search: "jane", status: "active" });
  });

  it("falls back to page 1 for a non-numeric, zero, negative, or decimal page value", () => {
    for (const raw of ["abc", "0", "-1", "1.5", "01"]) {
      expect(parseCustomerListParams(new URLSearchParams(`page=${raw}`)).page).toBe(1);
    }
  });

  it("falls back to 'all' for an unrecognized status value", () => {
    expect(parseCustomerListParams(new URLSearchParams("status=deleted")).status).toBe("all");
  });

  it("truncates an unreasonably long search value rather than forwarding it as-is", () => {
    const huge = "a".repeat(5000);
    const params = parseCustomerListParams(new URLSearchParams(`search=${huge}`));
    expect(params.search.length).toBeLessThanOrEqual(200);
  });
});

describe("buildCustomerListQueryString", () => {
  it("produces an empty string for default params", () => {
    expect(buildCustomerListQueryString({ page: 1, search: "", status: "all" })).toBe("");
  });

  it("omits defaulted fields and includes only the ones that differ", () => {
    expect(buildCustomerListQueryString({ page: 2, search: "", status: "all" })).toBe("?page=2");
    expect(buildCustomerListQueryString({ page: 1, search: "jane", status: "all" })).toBe(
      "?search=jane",
    );
    expect(buildCustomerListQueryString({ page: 1, search: "", status: "inactive" })).toBe(
      "?status=inactive",
    );
  });

  it("trims search before serializing", () => {
    expect(buildCustomerListQueryString({ page: 1, search: "  jane  ", status: "all" })).toBe(
      "?search=jane",
    );
  });
});
