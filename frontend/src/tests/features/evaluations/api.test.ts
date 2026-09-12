import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { fetchEvaluationResultList, fetchEvaluationRunDetail, fetchEvaluationRunList } from "@/features/evaluations/api";
import { server } from "@/tests/msw/server";

const BASE = "http://localhost:8000";

describe("fetchEvaluationRunList request shape", () => {
  it("omits page/status from the query string for default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchEvaluationRunList("ws-1", { page: 1, status: "all" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.has("page")).toBe(false);
    expect(params.has("status")).toBe(false);
    expect(params.has("search")).toBe(false);
    expect(params.has("ordering")).toBe(false);
  });

  it("sends page/status for non-default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchEvaluationRunList("ws-1", { page: 2, status: "running" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("page")).toBe("2");
    expect(params.get("status")).toBe("running");
  });
});

describe("fetchEvaluationRunDetail", () => {
  it("throws a not_found ApiError for a 404 response", async () => {
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/:runId/`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Evaluation run not found." } },
          { status: 404 },
        ),
      ),
    );

    await expect(fetchEvaluationRunDetail("ws-1", "run-1")).rejects.toMatchObject({
      code: "not_found",
    });
  });
});

describe("fetchEvaluationResultList request shape", () => {
  it("omits page/passed from the query string for default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(
        `${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/:runId/results/`,
        ({ request }) => {
          capturedUrl = new URL(request.url);
          return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
        },
      ),
    );

    await fetchEvaluationResultList("ws-1", "run-1", { page: 1, passed: "all" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.has("page")).toBe(false);
    expect(params.has("passed")).toBe(false);
  });

  it("sends a boolean passed query value for a non-default filter", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(
        `${BASE}/api/v1/workspaces/:workspaceId/evaluations/runs/:runId/results/`,
        ({ request }) => {
          capturedUrl = new URL(request.url);
          return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
        },
      ),
    );

    await fetchEvaluationResultList("ws-1", "run-1", { page: 1, passed: "failed" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("passed")).toBe("false");
  });
});
