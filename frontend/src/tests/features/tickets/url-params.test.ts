import { describe, expect, it } from "vitest";

import { buildTicketListQueryString, parseTicketListParams } from "@/features/tickets/url-params";

describe("parseTicketListParams", () => {
  it("defaults to page 1 and 'all' filters for an empty query string", () => {
    expect(parseTicketListParams(new URLSearchParams())).toEqual({
      page: 1,
      status: "all",
      priority: "all",
      customerId: null,
    });
  });

  it("round-trips valid params", () => {
    const customerId = "11111111-1111-4111-8111-111111111111";
    const params = parseTicketListParams(
      new URLSearchParams(`page=2&status=open&priority=urgent&customer=${customerId}`),
    );
    expect(params).toEqual({ page: 2, status: "open", priority: "urgent", customerId });
  });

  it("falls back to 'all' for an unrecognized status or priority value", () => {
    expect(parseTicketListParams(new URLSearchParams("status=archived")).status).toBe("all");
    expect(parseTicketListParams(new URLSearchParams("priority=critical")).priority).toBe("all");
  });

  it("falls back to page 1 for a non-numeric, zero, or negative page value", () => {
    for (const raw of ["abc", "0", "-1", "1.5"]) {
      expect(parseTicketListParams(new URLSearchParams(`page=${raw}`)).page).toBe(1);
    }
  });

  it("ignores a malformed customer ID rather than sending it to the backend — a URL value is not authorization", () => {
    expect(parseTicketListParams(new URLSearchParams("customer=not-a-uuid")).customerId).toBeNull();
    expect(parseTicketListParams(new URLSearchParams("customer=<script>")).customerId).toBeNull();
  });
});

describe("buildTicketListQueryString", () => {
  it("produces an empty string for default params", () => {
    expect(
      buildTicketListQueryString({ page: 1, status: "all", priority: "all", customerId: null }),
    ).toBe("");
  });

  it("omits defaulted fields and includes only the ones that differ", () => {
    expect(
      buildTicketListQueryString({ page: 2, status: "open", priority: "all", customerId: null }),
    ).toBe("?page=2&status=open");
  });

  it("includes a real customer filter", () => {
    const customerId = "11111111-1111-4111-8111-111111111111";
    expect(
      buildTicketListQueryString({ page: 1, status: "all", priority: "all", customerId }),
    ).toBe(`?customer=${customerId}`);
  });
});
