import { describe, expect, it } from "vitest";

import {
  buildEvaluationResultListQueryString,
  buildEvaluationRunListQueryString,
  parseEvaluationResultListParams,
  parseEvaluationRunListParams,
} from "@/features/evaluations/url-params";

describe("parseEvaluationRunListParams", () => {
  it("defaults page to 1 and status to all for an empty query string", () => {
    expect(parseEvaluationRunListParams(new URLSearchParams())).toEqual({
      page: 1,
      status: "all",
    });
  });

  it("parses a valid page and status", () => {
    expect(
      parseEvaluationRunListParams(new URLSearchParams("page=3&status=running")),
    ).toEqual({ page: 3, status: "running" });
  });

  it("falls back to defaults for malformed/unrecognized values", () => {
    expect(
      parseEvaluationRunListParams(new URLSearchParams("page=-1&status=not-a-status")),
    ).toEqual({ page: 1, status: "all" });
    expect(parseEvaluationRunListParams(new URLSearchParams("page=abc"))).toEqual({
      page: 1,
      status: "all",
    });
  });
});

describe("buildEvaluationRunListQueryString", () => {
  it("produces an empty string for default params", () => {
    expect(buildEvaluationRunListQueryString({ page: 1, status: "all" })).toBe("");
  });

  it("includes only the non-default params", () => {
    expect(buildEvaluationRunListQueryString({ page: 2, status: "failed" })).toBe(
      "?page=2&status=failed",
    );
  });
});

describe("parseEvaluationResultListParams", () => {
  it("defaults resultsPage to 1 and passed to all for an empty query string", () => {
    expect(parseEvaluationResultListParams(new URLSearchParams())).toEqual({
      page: 1,
      passed: "all",
    });
  });

  it("parses a valid resultsPage and passed filter, distinct from the run list's own page param", () => {
    expect(
      parseEvaluationResultListParams(new URLSearchParams("page=9&resultsPage=2&passed=failed")),
    ).toEqual({ page: 2, passed: "failed" });
  });

  it("falls back to defaults for malformed/unrecognized values", () => {
    expect(
      parseEvaluationResultListParams(new URLSearchParams("resultsPage=-1&passed=maybe")),
    ).toEqual({ page: 1, passed: "all" });
  });
});

describe("buildEvaluationResultListQueryString", () => {
  it("produces an empty string for default params", () => {
    expect(buildEvaluationResultListQueryString({ page: 1, passed: "all" })).toBe("");
  });

  it("includes only the non-default params, using the resultsPage/passed names", () => {
    expect(buildEvaluationResultListQueryString({ page: 2, passed: "passed" })).toBe(
      "?resultsPage=2&passed=passed",
    );
  });
});
