import { describe, expect, it } from "vitest";

import {
  buildAgentRunListQueryString,
  parseAgentRunListParams,
} from "@/features/agent-runs/url-params";

describe("parseAgentRunListParams", () => {
  it("defaults page to 1 and status to all for an empty query string", () => {
    expect(parseAgentRunListParams(new URLSearchParams())).toEqual({ page: 1, status: "all" });
  });

  it("parses a valid page and status", () => {
    expect(parseAgentRunListParams(new URLSearchParams("page=3&status=running"))).toEqual({
      page: 3,
      status: "running",
    });
  });

  it("falls back to defaults for malformed/unrecognized values", () => {
    expect(parseAgentRunListParams(new URLSearchParams("page=-1&status=not-a-status"))).toEqual({
      page: 1,
      status: "all",
    });
    expect(parseAgentRunListParams(new URLSearchParams("page=abc"))).toEqual({
      page: 1,
      status: "all",
    });
  });
});

describe("buildAgentRunListQueryString", () => {
  it("produces an empty string for default params", () => {
    expect(buildAgentRunListQueryString({ page: 1, status: "all" })).toBe("");
  });

  it("includes only the non-default params", () => {
    expect(buildAgentRunListQueryString({ page: 2, status: "failed" })).toBe(
      "?page=2&status=failed",
    );
  });
});
