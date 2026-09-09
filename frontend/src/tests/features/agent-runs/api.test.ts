import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { fetchAgentRunDetail, fetchAgentRunList } from "@/features/agent-runs/api";
import { server } from "@/tests/msw/server";

const BASE = "http://localhost:8000";

describe("fetchAgentRunList request shape", () => {
  it("omits page/status from the query string for default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/agent-runs/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchAgentRunList("ws-1", { page: 1, status: "all" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.has("page")).toBe(false);
    expect(params.has("status")).toBe(false);
    expect(params.has("search")).toBe(false);
    expect(params.has("ordering")).toBe(false);
  });

  it("sends page/status for non-default params", async () => {
    let capturedUrl: URL | null = null;
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/agent-runs/`, ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    await fetchAgentRunList("ws-1", { page: 2, status: "running" });

    const params = (capturedUrl as unknown as URL).searchParams;
    expect(params.get("page")).toBe("2");
    expect(params.get("status")).toBe("running");
  });
});

describe("fetchAgentRunDetail", () => {
  it("throws a not_found ApiError for a 404 response", async () => {
    server.use(
      http.get(`${BASE}/api/v1/workspaces/:workspaceId/agent-runs/:runId/`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Agent run not found." } },
          { status: 404 },
        ),
      ),
    );

    await expect(fetchAgentRunDetail("ws-1", "run-1")).rejects.toMatchObject({
      code: "not_found",
    });
  });
});
