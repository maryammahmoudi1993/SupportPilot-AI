import { describe, expect, it } from "vitest";

import {
  buildConversationListQueryString,
  parseConversationListParams,
  parseMessagePage,
} from "@/features/conversations/url-params";

describe("parseConversationListParams", () => {
  it("defaults to page 1 and 'all' filters for an empty query string", () => {
    expect(parseConversationListParams(new URLSearchParams())).toEqual({
      page: 1,
      status: "all",
      channel: "all",
      assignment: "all",
    });
  });

  it("round-trips valid params", () => {
    const params = parseConversationListParams(
      new URLSearchParams("page=2&status=open&channel=email&assigned=unassigned"),
    );
    expect(params).toEqual({ page: 2, status: "open", channel: "email", assignment: "unassigned" });
  });

  it("falls back to 'all' for an unrecognized status or channel value", () => {
    expect(parseConversationListParams(new URLSearchParams("status=archived")).status).toBe("all");
    expect(parseConversationListParams(new URLSearchParams("channel=carrier-pigeon")).channel).toBe(
      "all",
    );
  });

  it("falls back to 'all' assignment for anything other than 'unassigned'", () => {
    expect(parseConversationListParams(new URLSearchParams("assigned=mine")).assignment).toBe("all");
  });

  it("falls back to page 1 for a non-numeric, zero, or negative page value", () => {
    for (const raw of ["abc", "0", "-1", "1.5"]) {
      expect(parseConversationListParams(new URLSearchParams(`page=${raw}`)).page).toBe(1);
    }
  });
});

describe("buildConversationListQueryString", () => {
  it("produces an empty string for default params", () => {
    expect(
      buildConversationListQueryString({ page: 1, status: "all", channel: "all", assignment: "all" }),
    ).toBe("");
  });

  it("omits defaulted fields and includes only the ones that differ", () => {
    expect(
      buildConversationListQueryString({
        page: 2,
        status: "open",
        channel: "all",
        assignment: "all",
      }),
    ).toBe("?page=2&status=open");
    expect(
      buildConversationListQueryString({
        page: 1,
        status: "all",
        channel: "all",
        assignment: "unassigned",
      }),
    ).toBe("?assigned=unassigned");
  });
});

describe("parseMessagePage", () => {
  it("defaults to 1 and validates like the list page param", () => {
    expect(parseMessagePage(new URLSearchParams())).toBe(1);
    expect(parseMessagePage(new URLSearchParams("page=3"))).toBe(3);
    expect(parseMessagePage(new URLSearchParams("page=abc"))).toBe(1);
  });
});
